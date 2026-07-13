"""Shadow whale: sigue los fills de direcciones objetivo en vivo (dato público).

Hyperliquid es transparente: userFills de CUALQUIER dirección es suscribible
por WebSocket. Este módulo mantiene un tape rodante por dirección para que el
dashboard pinte qué hacen las whales elegidas. Solo OBSERVA — el modo espejo
(replicar a escala) queda para una fase posterior.

Direcciones vía HL_WATCH_ADDRESSES (coma-separadas) en bot/.env. En testnet
se puede verificar con la propia dirección del bot (sus fills aparecen).
Misma política de reconexión que marketdata (el SDK no reconecta solo).
"""
from __future__ import annotations
import threading
import time
from collections import deque

from hyperliquid.websocket_manager import WebsocketManager

FILLS_PER_ADDRESS = 50
RESTART_AFTER_S = 60.0   # userFills puede callar mucho rato legítimamente:
                         # solo reconectar si el socket está muerto de verdad


class WhaleWatch:
    def __init__(self, base_url: str, addresses: list[str]):
        self.base_url = base_url
        self.addresses = [a.lower() for a in addresses if a]
        self._lock = threading.Lock()
        self._fills: dict[str, deque] = {a: deque(maxlen=FILLS_PER_ADDRESS)
                                         for a in self.addresses}
        self._seen: dict[str, set] = {a: set() for a in self.addresses}
        self._ws: WebsocketManager | None = None
        self._last_restart = 0.0

    def start(self) -> None:
        if not self.addresses:
            return
        self._connect()

    def _connect(self) -> None:
        ws = WebsocketManager(self.base_url)
        ws.daemon = True
        ws.ping_sender.daemon = True
        ws.start()
        for a in self.addresses:
            ws.subscribe({"type": "userFills", "user": a}, self._on_fills)
        self._ws = ws
        self._last_restart = time.time()

    def stop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                pass
            self._ws = None

    def ensure_alive(self) -> None:
        if not self.addresses or self._ws is None:
            return
        alive = getattr(getattr(self._ws, "ws", None), "keep_running", False)
        if alive or time.time() - self._last_restart < RESTART_AFTER_S:
            return
        print("[whales] socket muerto, reconectando", flush=True)
        self.stop()
        try:
            self._connect()
        except Exception as e:
            self._last_restart = time.time()
            print(f"[whales] reconexión fallida: {e}", flush=True)

    def _on_fills(self, msg: dict) -> None:
        data = msg.get("data") or {}
        user = str(data.get("user", "")).lower()
        with self._lock:
            tape = self._fills.get(user)
            seen = self._seen.get(user)
            if tape is None:
                return
            for f in data.get("fills") or []:
                key = str(f.get("tid") or f.get("hash") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                if len(seen) > FILLS_PER_ADDRESS * 4:
                    seen.clear()
                    seen.update(str(x.get("tid", "")) for x in tape)
                tape.append({
                    "ts": int(f.get("time", 0) or 0) // 1000,
                    "coin": f.get("coin"),
                    "side": f.get("side"),
                    "px": float(f.get("px", 0) or 0),
                    "sz": float(f.get("sz", 0) or 0),
                    "dir": f.get("dir", ""),
                    "closed_pnl": float(f.get("closedPnl", 0) or 0),
                    "tid": key,
                })

    def recent(self) -> dict[str, list[dict]]:
        """Fills recientes por dirección, el más nuevo primero."""
        with self._lock:
            return {a: list(reversed(t)) for a, t in self._fills.items()}
