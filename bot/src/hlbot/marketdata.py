"""Caché de microestructura en vivo por WebSocket: bbo, tape, vol realizada.

Alimenta al engine con precio/flujo de sub-segundo sin gastar presupuesto REST.
Todos los getters devuelven None cuando el dato está stale (>MAX_AGE_S) o aún no
llegó: el llamador degrada a REST/ATR. El backtester nunca construye este objeto,
así que las estrategias tienen que funcionar igual sin él.

El WebsocketManager del SDK NO reconecta solo: ensure_alive() (llamado por el
runner en cada tick) reconstruye la conexión si el socket está muerto
(keep_running=False) o si NO llega NINGÚN mensaje en RESTART_AFTER_S, con
throttle para no ciclar en una caída larga de red. La señal de vida es
"llegan mensajes", no "llegan datos": el SDK descarta los pongs del servidor
(uno por ping cada 50s) antes de los callbacks, y en testnet el BBO puede no
cambiar en minutos — sin contar los pongs, mercado callado parecía conexión
muerta y se reconectaba cada ~11 min (369 veces en el soak de la sesión 5).

GOTCHA (verificado 2026-07-13): suscribirse a un coin que no existe en el
universo hace que HL cierre el websocket ENTERO sin mensaje de error (XRP no
existe en testnet). El constructor debe recibir monedas ya filtradas contra
el meta (client.sz_decimals).
"""
from __future__ import annotations
import math
import threading
import time
from collections import deque

from hyperliquid.websocket_manager import WebsocketManager

MAX_AGE_S = 3.0           # frescura máxima para servir un dato
RESTART_AFTER_S = 150.0   # sin NINGÚN mensaje (ni pongs, cada 50s) -> reconectar
RECONNECT_THROTTLE_S = 30.0   # mínimo entre reconexiones
VOL_HALFLIFE_S = 60.0     # semivida de la EWMA de varianza realizada
TAPE_RETENTION_S = 60.0   # cuánto tape se retiene (la ventana de lectura es menor)
PX_HIST_RETENTION_S = 180.0   # histórico de mids para markouts (+5s/+30s/+120s)
PX_HIST_MIN_GAP_S = 0.5       # muestreo máximo del histórico (bbo puede ser muy denso)


class _LivenessWS(WebsocketManager):
    """WebsocketManager que notifica CUALQUIER mensaje entrante.

    El on_message del SDK descarta pongs y el saludo de conexión antes de
    llegar a los callbacks de suscripción; para medir vida de la conexión
    hacen falta TODOS los mensajes.
    """

    def __init__(self, base_url: str, on_any_message):
        super().__init__(base_url)
        self._on_any_message = on_any_message

    def on_message(self, ws, message):
        self._on_any_message()
        super().on_message(ws, message)


class MarketData:
    def __init__(self, base_url: str, coins: list[str]):
        self.base_url = base_url
        self.coins = list(coins)
        self._lock = threading.Lock()
        self._bbo: dict[str, dict] = {}
        self._tape: dict[str, deque] = {c: deque() for c in self.coins}
        self._px_hist: dict[str, deque] = {c: deque() for c in self.coins}
        # coin -> (varianza por segundo EWMA, último mid, ts del último mid)
        self._vol: dict[str, tuple[float, float, float]] = {}
        self._last_msg_ts = 0.0
        self._last_restart = 0.0
        self._ws: WebsocketManager | None = None
        self.reconnects = 0   # reconexiones acumuladas (salud del feed, queryable)

    # ---------- conexión ----------

    def start(self) -> None:
        self._connect()

    def _connect(self) -> None:
        ws = _LivenessWS(self.base_url, self._touch)
        # daemon: que el proceso pueda salir aunque el WS siga vivo
        ws.daemon = True
        ws.ping_sender.daemon = True
        ws.start()
        for c in self.coins:
            ws.subscribe({"type": "bbo", "coin": c}, self._on_bbo)
            ws.subscribe({"type": "trades", "coin": c}, self._on_trades)
        self._ws = ws
        self._last_msg_ts = time.time()   # gracia: no reconectar antes del primer dato
        self._last_restart = time.time()

    def stop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                pass
            self._ws = None

    def _touch(self) -> None:
        self._last_msg_ts = time.time()

    def ensure_alive(self) -> None:
        now = time.time()
        dead = (self._ws is not None
                and not getattr(getattr(self._ws, "ws", None), "keep_running", False))
        if not dead and now - self._last_msg_ts < RESTART_AFTER_S:
            return
        if now - self._last_restart < RECONNECT_THROTTLE_S:
            return   # throttle: una reconexión por ventana, no un bucle
        print("[marketdata] socket muerto o feed callado, reconectando", flush=True)
        self.stop()
        try:
            self._connect()
            self.reconnects += 1
        except Exception as e:
            self._last_restart = now
            print(f"[marketdata] reconexión fallida: {e}", flush=True)

    # ---------- callbacks WS ----------

    def _on_bbo(self, msg: dict) -> None:
        data = msg.get("data") or {}
        coin = data.get("coin")
        bbo = data.get("bbo") or [None, None]
        bid, ask = (bbo + [None, None])[:2]
        now = time.time()
        with self._lock:
            self._last_msg_ts = now
            if not coin or not bid or not ask:
                return
            bpx, bsz = float(bid["px"]), float(bid["sz"])
            apx, asz = float(ask["px"]), float(ask["sz"])
            self._bbo[coin] = {"bid_px": bpx, "bid_sz": bsz,
                               "ask_px": apx, "ask_sz": asz, "ts": now}
            mid = (bpx + apx) / 2.0
            hist = self._px_hist.setdefault(coin, deque())
            if not hist or now - hist[-1][0] >= PX_HIST_MIN_GAP_S:
                hist.append((now, mid))
                cutoff = now - PX_HIST_RETENTION_S
                while hist and hist[0][0] < cutoff:
                    hist.popleft()
            var, last_mid, last_ts = self._vol.get(coin, (0.0, 0.0, 0.0))
            if last_mid > 0 and mid > 0:
                dt = max(now - last_ts, 1e-3)
                r2s = (math.log(mid / last_mid) ** 2) / dt   # var instantánea /s
                alpha = 1 - 0.5 ** (dt / VOL_HALFLIFE_S)
                var = (1 - alpha) * var + alpha * r2s
            self._vol[coin] = (var, mid, now)

    def _on_trades(self, msg: dict) -> None:
        now = time.time()
        with self._lock:
            self._last_msg_ts = now
            for t in msg.get("data") or []:
                coin = t.get("coin")
                tape = self._tape.get(coin)
                if tape is None:
                    continue
                usd = float(t["px"]) * float(t["sz"])
                sign = 1.0 if t.get("side") == "B" else -1.0   # B = agresor comprador
                tape.append((now, sign * usd))
                cutoff = now - TAPE_RETENTION_S
                while tape and tape[0][0] < cutoff:
                    tape.popleft()

    # ---------- getters (None si stale o sin datos) ----------

    def bbo(self, coin: str) -> dict | None:
        with self._lock:
            b = self._bbo.get(coin)
            if not b or time.time() - b["ts"] > MAX_AGE_S:
                return None
            return dict(b)

    def mid(self, coin: str) -> float | None:
        b = self.bbo(coin)
        return (b["bid_px"] + b["ask_px"]) / 2.0 if b else None

    def microprice(self, coin: str) -> float | None:
        # Mid ponderado por el desequilibrio del BBO: si el bid tiene mucho más
        # tamaño que el ask, el "precio justo" está más cerca del ask.
        b = self.bbo(coin)
        if not b:
            return None
        denom = b["bid_sz"] + b["ask_sz"]
        if denom <= 0:
            return (b["bid_px"] + b["ask_px"]) / 2.0
        return (b["bid_px"] * b["ask_sz"] + b["ask_px"] * b["bid_sz"]) / denom

    def sigma_px(self, coin: str, horizon_s: float = 60.0) -> float | None:
        # Vol realizada EWMA proyectada al horizonte, en unidades de PRECIO
        # (comparable al ATR que usan las estrategias como fallback).
        b = self.bbo(coin)
        if not b:
            return None
        with self._lock:
            var, last_mid, _ = self._vol.get(coin, (0.0, 0.0, 0.0))
        if var <= 0 or last_mid <= 0:
            return None
        return last_mid * math.sqrt(var * horizon_s)

    def flow(self, coin: str, window_s: float = 15.0) -> tuple[float, float]:
        """(USD firmado, USD total) del tape en la ventana. (0, 0) sin trades."""
        cutoff = time.time() - min(window_s, TAPE_RETENTION_S)
        signed = total = 0.0
        with self._lock:
            for ts, susd in self._tape.get(coin, ()):
                if ts >= cutoff:
                    signed += susd
                    total += abs(susd)
        return signed, total

    def mid_at(self, coin: str, ts: float, tol_s: float = 2.0) -> float | None:
        """Mid histórico más cercano a ts (para markouts). None si no hay muestra
        a menos de tol_s (hueco del feed o ts fuera de la retención)."""
        with self._lock:
            hist = self._px_hist.get(coin)
            if not hist:
                return None
            best_ts, best_px = min(hist, key=lambda p: abs(p[0] - ts))
        return best_px if abs(best_ts - ts) <= tol_s else None

    def ws_age(self) -> float:
        return time.time() - self._last_msg_ts if self._last_msg_ts else float("inf")
