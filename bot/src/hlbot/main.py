from __future__ import annotations
import asyncio
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
TICK_SECONDS = 5
PNL_SNAPSHOT_EVERY = 12                 # ~cada minuto a 5s/tick
ACCOUNT_EXTRAS_EVERY = 6               # cada cuántos ticks refrescar fills/funding (más pesados)
API_PORT = 3300


def refresh_account_cache(client, engine, cache: dict, fetch_extras: bool) -> None:
    try:
        ch = client.user_state()
    except Exception as e:
        print(f"[account_cache] user_state error: {e}", flush=True)
        return
    if fetch_extras:
        try:
            cache["_fills"] = client.user_fills()
            funding = client.user_funding(0)
            cache["_funding"] = sum(float(f.get("delta", {}).get("usdc", 0) or 0) for f in funding)
        except Exception as e:
            print(f"[account_cache] extras error: {e}", flush=True)
    fills = cache.get("_fills", [])
    funding_total = cache.get("_funding", 0.0)
    max_open = engine.cfg.limits.max_open_positions if engine.cfg else 0
    acc = compose_account(ch, fills, funding_total, engine.session_start_value, max_open)
    acc["_fills"] = fills
    acc["_funding"] = funding_total
    cache.clear()
    cache.update(acc)


def candles_to_models(raw: list[dict]) -> list[Candle]:
    out: list[Candle] = []
    for c in raw:
        out.append(Candle(t=int(c["t"]), open=float(c["o"]), high=float(c["h"]),
                          low=float(c["l"]), close=float(c["c"]), volume=float(c["v"])))
    return out


def build_market_state(client, coin: str, now_ms: int) -> tuple[MarketState, list[dict]]:
    mid = client.mid(coin)
    raw = client.candles(coin, CANDLE_INTERVAL, now_ms - CANDLE_LOOKBACK_MS, now_ms)
    return MarketState(coin=coin, mid=mid, candles=candles_to_models(raw)), raw


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


async def _trade_loop(engine: SessionEngine, client: HLClient, store: Store,
                      shared: dict[str, MarketState], account_cache: dict) -> None:
    ticks = 0
    while True:
        try:
            coins = engine.cfg.watchlist if engine.cfg else []
            now_ms = int(time.time() * 1000)
            states: dict[str, MarketState] = {}
            for coin in coins:
                ms, raw = build_market_state(client, coin, now_ms)
                states[coin] = ms
                shared[coin] = ms
                persist_candles(store, coin, raw)
            if states:
                engine.tick(states)
                ticks += 1
                if ticks % PNL_SNAPSHOT_EVERY == 0 and engine.session_id is not None:
                    store.record_pnl_snapshot(engine.session_id, engine._account_value())
            refresh_account_cache(client, engine, account_cache,
                                  fetch_extras=(ticks % ACCOUNT_EXTRAS_EVERY == 0))
        except Exception as e:  # red caída, etc.: log y seguir
            print(f"[trade_loop] error: {e}", flush=True)
        await asyncio.sleep(TICK_SECONDS)


def main() -> None:
    cfg = Config.from_env()
    client = HLClient(cfg)
    store = Store(cfg.db_path)
    store.init_schema()
    engine = SessionEngine(client, store)
    shared: dict[str, MarketState] = {}
    account_cache: dict = {}

    app = create_app(engine, cfg.control_token, lambda: shared, lambda: account_cache)

    @app.on_event("startup")
    async def _start_loop():
        asyncio.create_task(_trade_loop(engine, client, store, shared, account_cache))

    uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
