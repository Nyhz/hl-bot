from __future__ import annotations
import asyncio
import json
import os
import time

import uvicorn

from hlbot.config import Config
from hlbot.hl_client import HLClient
from hlbot.store import Store
from hlbot.session_engine import SessionEngine
from hlbot.api import create_app
from hlbot.models import MarketState, Candle
from hlbot.account import compose_account

CANDLE_INTERVAL = "1m"
CANDLE_LOOKBACK_MS = 1000 * 60 * 120   # 120 minutos de velas 1m
CANDLE_REFRESH_MS = 30_000             # velas 1m por REST cada 30s, no cada tick (pesan 20)
FUNDING_REFRESH_S = 60.0               # funding cambia lento; metaAndAssetCtxs pesa 20
FLOW_READ_WINDOW_S = 15.0              # ventana de lectura del tape para flow_ratio
MARKOUT_HORIZONS_S = (5, 30, 120)      # bps a favor del fill a +5s/+30s/+120s
TICK_SECONDS = 5
PNL_SNAPSHOT_EVERY = 12                 # ~cada minuto a 5s/tick
ACCOUNT_EXTRAS_EVERY = 6               # cada cuántos ticks refrescar fills/funding (más pesados)
DMS_EVERY_TICKS = 12                   # re-armar el dead man's switch cada ~60s
DMS_HORIZON_MS = 180_000               # sin re-arme en 3 min, HL cancela todo el reposo
HEARTBEAT_FILE = os.path.expanduser("~/.hlbot/heartbeat")
API_PORT = 3300


def refresh_account_cache(client, engine, prev: dict, fetch_extras: bool,
                          store=None) -> dict:
    try:
        ch = client.user_state()
    except Exception as e:
        print(f"[account_cache] user_state error: {e}", flush=True)
        return prev
    # Sin sesión (post kill/close/reinicio) los extras de la sesión anterior sobran,
    # pero equity y posiciones deben seguir reflejando el exchange real.
    in_session = engine.session_started_at is not None
    session_start_ms = int((engine.session_started_at or 0) * 1000)
    fills = prev.get("_fills", []) if in_session else []
    funding_total = prev.get("_funding", 0.0) if in_session else 0.0
    if fetch_extras and in_session:
        try:
            all_fills = client.user_fills()
            fills = [f for f in all_fills if int(f.get("time", 0) or 0) >= session_start_ms]
            funding = client.user_funding(session_start_ms)
            funding_total = sum(float(f.get("delta", {}).get("usdc", 0) or 0) for f in funding)
            if store is not None and engine.session_id is not None:
                _record_extras(store, engine.session_id, fills, funding)
        except Exception as e:
            print(f"[account_cache] extras error: {e}", flush=True)
    max_open = engine.cfg.limits.max_open_positions if engine.cfg else 0
    acc = compose_account(ch, fills, funding_total, engine.session_start_value, max_open)
    if not in_session:
        acc["session_pnl"] = 0.0
    acc["_fills"] = fills
    acc["_funding"] = funding_total
    return acc


def _record_extras(store, session_id: int, fills: list[dict], funding: list[dict]) -> None:
    for f in fills:
        tid = str(f.get("tid") if f.get("tid") is not None else f.get("hash", ""))
        if not tid:
            continue
        store.record_fill_unique(
            session_id, tid, int(f.get("time", 0) or 0) // 1000, f.get("coin"),
            f.get("side", ""), f.get("dir", ""), float(f.get("px", 0) or 0),
            float(f.get("sz", 0) or 0), float(f.get("fee", 0) or 0),
            float(f.get("closedPnl", 0) or 0))
    for fp in funding:
        delta = fp.get("delta", {}) or {}
        fkey = str(fp.get("hash") or f"{fp.get('time','')}-{delta.get('coin','')}")
        store.record_funding_unique(
            session_id, fkey, int(fp.get("time", 0) or 0) // 1000,
            delta.get("coin", ""), float(delta.get("usdc", 0) or 0))


def candles_to_models(raw: list[dict]) -> list[Candle]:
    out: list[Candle] = []
    for c in raw:
        out.append(Candle(t=int(c["t"]), open=float(c["o"]), high=float(c["h"]),
                          low=float(c["l"]), close=float(c["c"]), volume=float(c["v"])))
    return out


def build_market_state(client, coin: str, now_ms: int, md=None,
                       candle_cache: dict | None = None) -> tuple[MarketState, list[dict], bool]:
    """Estado de mercado del tick. Devuelve (ms, velas_raw, velas_refrescadas).

    Con WebSocket fresco el mid sale del bbo (sub-segundo, sin REST) y se pueblan
    los campos de microestructura; sin él, degrada al REST de siempre. Las velas
    1m se refrescan cada CANDLE_REFRESH_MS (cambiarlas cada tick es tirar weight).
    """
    ent = candle_cache.get(coin) if candle_cache is not None else None
    refreshed = not (ent and now_ms - ent[0] < CANDLE_REFRESH_MS)
    if refreshed:
        raw = client.candles(coin, CANDLE_INTERVAL, now_ms - CANDLE_LOOKBACK_MS, now_ms)
        if candle_cache is not None:
            candle_cache[coin] = (now_ms, raw)
    else:
        raw = ent[1]
    ms = MarketState(coin=coin, mid=0.0, candles=candles_to_models(raw))
    if md is not None:
        b = md.bbo(coin)
        if b:
            ms.best_bid, ms.bid_sz = b["bid_px"], b["bid_sz"]
            ms.best_ask, ms.ask_sz = b["ask_px"], b["ask_sz"]
            ms.mid = (b["bid_px"] + b["ask_px"]) / 2.0
            ms.microprice = md.microprice(coin)
            ms.sigma_px = md.sigma_px(coin)
            signed, total = md.flow(coin, FLOW_READ_WINDOW_S)
            ms.flow_usd = signed
            ms.flow_total_usd = total
            ms.flow_ratio = (signed / total) if total > 0 else None
    if ms.mid <= 0:
        ms.mid = client.mid(coin)   # fallback REST (WS frío o sin marketdata)
    return ms, raw, refreshed


def persist_candles(store: Store, coin: str, raw: list[dict]) -> None:
    with store._conn() as conn:
        for c in raw:
            conn.execute(
                "INSERT OR REPLACE INTO market_candles "
                "(coin, interval, t, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (coin, CANDLE_INTERVAL, int(c["t"]), float(c["o"]), float(c["h"]),
                 float(c["l"]), float(c["c"]), float(c["v"])),
            )


def refresh_dead_man_switch(engine, client, counters) -> None:
    # Dead man's switch del exchange: con sesión activa se re-arma un cancel-all
    # diferido; si el proceso muere o se congela, la escalera del grid deja de
    # llenarse sola. Sin sesión se desarma (no interferir con órdenes manuales).
    # OJO: HL lo gatea a $1M de volumen acumulado; si lo rechaza, se desactiva
    # para el resto del proceso y la protección queda en el watchdog local
    # (hlbot.watchdog), que cumple la misma función leyendo el heartbeat.
    if counters.get("dms_unavailable"):
        return
    now_ms = int(time.time() * 1000)
    in_session = engine.cfg is not None
    armed = counters.get("dms_armed", False)
    stale = armed and now_ms - counters.get("dms_last_arm_ms", now_ms) > DMS_HORIZON_MS
    if stale:
        # El horizonte venció con el bot vivo (tick congelado >3 min): el exchange ya
        # canceló los stops de tendencia; olvidarlos para que el engine los recoloque.
        engine.stop_levels.clear()
        engine.stop_oids.clear()
    try:
        if in_session and (not armed or stale
                           or counters["loop"] % DMS_EVERY_TICKS == 0):
            resp = client.schedule_cancel(now_ms + DMS_HORIZON_MS)
            if isinstance(resp, dict) and resp.get("status") != "ok":
                counters["dms_unavailable"] = True
                print(f"[dms] no disponible (protege el watchdog): "
                      f"{resp.get('response')}", flush=True)
                return
            counters["dms_armed"] = True
            counters["dms_last_arm_ms"] = now_ms
        elif not in_session and armed:
            client.schedule_cancel(None)
            counters["dms_armed"] = False
    except Exception as e:
        print(f"[dms] error: {e}", flush=True)


def write_heartbeat() -> None:
    # Latido para hlbot.watchdog: "el tick completó una vuelta". Si deja de
    # escribirse (proceso muerto o congelado), el watchdog cancela el reposo.
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError as e:
        print(f"[heartbeat] error: {e}", flush=True)


def orphan_check(client, notifier) -> None:
    # Sin sesión que reanudar: si el exchange tiene restos (reinicio con sesión
    # antigua no rehidratable), cancelar el reposo y avisar. Las posiciones no se
    # liquidan solas: eso es decisión del usuario (Kill ya soporta huérfanas).
    try:
        orders = client.all_open_orders()
        positions = client.user_state().get("assetPositions", [])
    except Exception as e:
        print(f"[startup] orphan check error: {e}", flush=True)
        return
    for o in orders:
        try:
            client.cancel_order(o["coin"], o["oid"])
        except Exception as e:
            print(f"[startup] cancel {o.get('coin')}/{o.get('oid')}: {e}", flush=True)
    pos_coins = sorted({c for c in ((p.get("position", {}) or {}).get("coin")
                                    for p in positions) if c})
    if orders or pos_coins:
        msg = f"restos sin sesion: {len(orders)} ordenes en reposo canceladas"
        if pos_coins:
            msg += f"; posiciones huerfanas en {', '.join(pos_coins)} (usa Kill)"
        print(f"[startup] {msg}", flush=True)
        notifier(msg)


def recover_session(engine, client, store, cfg, notifier=None) -> None:
    # Al arrancar: rehidratar la última sesión viva del MODO actual, o modo seguro.
    if notifier is None:
        from hlbot.watchdog import notify as notifier
    mode = "testnet" if cfg.testnet else "mainnet"
    rows = store.open_sessions(mode)
    for s in rows[1:]:   # huérfanas más viejas acumuladas por crashes: archivar
        store.record_risk_event(s["id"], "huerfana",
                                "archivada al arrancar (hay otra sesion mas reciente)")
        store.end_session(s["id"])
    if not rows:
        orphan_check(client, notifier)
        return
    latest = rows[0]
    if not latest.get("payload"):
        # sesión de una versión sin runtime persistido: no rehidratable
        store.record_risk_event(latest["id"], "huerfana",
                                "sin runtime persistido: no rehidratable")
        store.end_session(latest["id"])
        notifier(f"sesion {latest['id']} huerfana archivada; revisando restos")
        orphan_check(client, notifier)
        return
    try:
        engine.rehydrate(latest["id"], int(latest["started_at"]),
                         json.loads(latest["payload"]))
        store.record_risk_event(latest["id"], "rehydrate",
                                "sesion rehidratada tras reinicio")
        print(f"[startup] sesion {latest['id']} rehidratada", flush=True)
        notifier(f"sesion {latest['id']} rehidratada tras reinicio")
    except Exception as e:
        # payload corrupto/incompatible: no operar a ciegas — archivar y limpiar
        engine._reset()
        store.record_risk_event(latest["id"], "rehydrate", f"fallo: {e}")
        store.end_session(latest["id"])
        print(f"[startup] rehidratacion fallida: {e}", flush=True)
        notifier(f"rehidratacion de sesion {latest['id']} FALLIDA; revisando restos")
        orphan_check(client, notifier)


def update_markouts(store, md, session_id) -> None:
    # Markout = evolución del mid tras cada fill, en bps FIRMADOS a favor del
    # fill (comprar y que luego suba = positivo). Sistemáticamente negativo =
    # selección adversa medida: EL número que dice si el grid pierde por tóxico.
    if md is None or session_id is None:
        return
    from hlbot.marketdata import PX_HIST_RETENTION_S
    now = time.time()
    for h in MARKOUT_HORIZONS_S:
        pending = store.fills_missing_markout(session_id, h, now,
                                              PX_HIST_RETENTION_S - h)
        for f in pending:
            ref = md.mid_at(f["coin"], f["ts"] + h)
            if ref is None or not f["price"]:
                continue   # hueco del feed: quedará NULL al salir de la ventana
            sign = 1.0 if f["side"] == "B" else -1.0
            bps = sign * (ref - f["price"]) / f["price"] * 1e4
            store.set_fill_markout(f["id"], h, bps)


def run_tick(engine, client, store, shared, cache_holder, counters,
             md=None, candle_cache: dict | None = None,
             funding_cache: dict | None = None):
    if md is not None:
        md.ensure_alive()   # el WS del SDK no reconecta solo
    with engine.lock:
        try:
            counters["loop"] += 1
            refresh_dead_man_switch(engine, client, counters)
            coins = engine.cfg.watchlist if engine.cfg else []
            now_ms = int(time.time() * 1000)
            funding: dict[str, float] = {}
            if coins:
                fresh = (funding_cache is not None
                         and time.time() - funding_cache.get("ts", 0) <= FUNDING_REFRESH_S)
                if fresh:
                    funding = funding_cache.get("v", {})
                else:
                    try:
                        funding = client.funding_rates()
                        if funding_cache is not None:
                            funding_cache["ts"] = time.time()
                            funding_cache["v"] = funding
                    except Exception as e:
                        print(f"[trade_loop] funding error: {e}", flush=True)
                        funding = (funding_cache or {}).get("v", {})
            states: dict[str, MarketState] = {}
            for coin in coins:
                ms, raw, refreshed = build_market_state(client, coin, now_ms, md, candle_cache)
                ms.funding_rate = funding.get(coin)
                states[coin] = ms
                shared[coin] = ms
                if refreshed:
                    persist_candles(store, coin, raw)
            if states:
                engine.tick(states)
                counters["ticks"] += 1
                if counters["ticks"] % PNL_SNAPSHOT_EVERY == 0 and engine.session_id is not None:
                    store.record_pnl_snapshot(engine.session_id, engine._account_value())
            # Refresco SIEMPRE (haya o no sesión): si solo se refrescara con cfg,
            # tras kill/close la caché quedaría congelada con las posiciones viejas
            # y el dashboard las pintaría como abiertas indefinidamente.
            cache_holder["v"] = refresh_account_cache(
                client, engine, cache_holder["v"],
                fetch_extras=(counters["loop"] % ACCOUNT_EXTRAS_EVERY == 0), store=store)
            update_markouts(store, md, engine.session_id)
            write_heartbeat()
        except Exception as e:  # red caída, BD, etc.: log y seguir
            print(f"[trade_loop] error: {e}", flush=True)


async def _trade_loop(engine: SessionEngine, client: HLClient, store: Store,
                      shared: dict[str, MarketState], cache_holder: dict,
                      md=None) -> None:
    counters = {"loop": 0, "ticks": 0}
    candle_cache: dict = {}
    funding_cache: dict = {}
    while True:
        await asyncio.to_thread(run_tick, engine, client, store, shared,
                                cache_holder, counters, md, candle_cache,
                                funding_cache)
        await asyncio.sleep(TICK_SECONDS)


def main() -> None:
    cfg = Config.from_env()
    client = HLClient(cfg)
    store = Store(cfg.db_path)
    store.init_schema()
    engine = SessionEngine(client, store)
    recover_session(engine, client, store, cfg)
    shared: dict[str, MarketState] = {}
    cache_holder: dict = {"v": {}}

    from hlbot.api import LIQUID_MAJORS
    from hlbot.marketdata import MarketData
    # Solo monedas del universo real: una suscripción a un coin inexistente
    # (p.ej. XRP en testnet) hace que HL cierre el websocket ENTERO.
    md_coins = [c for c in LIQUID_MAJORS if c in getattr(client, "sz_decimals", {})]
    md = MarketData(cfg.base_url, md_coins)
    try:
        md.start()
    except Exception as e:
        # sin WS el bot sigue operando por REST (los campos micro quedan None)
        print(f"[marketdata] no arrancó, seguimos por REST: {e}", flush=True)

    app = create_app(engine, cfg.control_token, lambda: shared, lambda: cache_holder["v"])

    @app.on_event("startup")
    async def _start_loop():
        asyncio.create_task(_trade_loop(engine, client, store, shared, cache_holder, md))

    uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
