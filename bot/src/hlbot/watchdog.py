"""Watchdog independiente del bot (dead man's switch local).

El scheduleCancel nativo de Hyperliquid exige $1M de volumen acumulado —
inalcanzable con rungs de $10 — así que este proceso cubre su función:
launchd lo ejecuta cada minuto (com.hlbot.watchdog); si el heartbeat que
escribe run_tick lleva más de STALE_SECONDS sin latir, cancela todas las
órdenes EN REPOSO y avisa con una notificación de macOS.

Los stops trigger reduce-only NO se tocan: con el bot muerto son la única
protección de la posición (y no aparecen en open_orders básico, solo en
frontend_open_orders, así que quedan fuera por construcción).

Un latch evita repetir cancelación y aviso cada minuto durante la misma
caída; al volver el latido se limpia y se notifica la recuperación.
"""
from __future__ import annotations
import os
import subprocess
import time

STATE_DIR = os.path.expanduser("~/.hlbot")
HEARTBEAT_FILE = os.path.join(STATE_DIR, "heartbeat")
LATCH_FILE = os.path.join(STATE_DIR, "watchdog_latch")
STALE_SECONDS = 180


def heartbeat_age(now: float, path: str = HEARTBEAT_FILE) -> float:
    try:
        with open(path) as f:
            return now - float(f.read().strip())
    except (OSError, ValueError):
        return float("inf")


def notify(msg: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "hl-bot watchdog"'],
            check=False, timeout=10)
    except Exception:
        pass


def check_once(client_factory, now: float, hb_path: str = HEARTBEAT_FILE,
               latch_path: str = LATCH_FILE, notifier=notify) -> str:
    age = heartbeat_age(now, hb_path)
    if age <= STALE_SECONDS:
        if os.path.exists(latch_path):
            os.remove(latch_path)
            notifier("bot recuperado: el latido ha vuelto")
        return "ok"
    if os.path.exists(latch_path):
        return "latched"
    # El cliente solo se construye en el camino caído (evita pegar a la API de
    # HL cada minuto solo para mirar un fichero local).
    client = client_factory()
    orders = client.info.open_orders(client.address)
    canceled = 0
    for o in orders:
        try:
            client.cancel_order(o["coin"], o["oid"])
            canceled += 1
        except Exception:
            pass
    mins = "?" if age == float("inf") else str(int(age // 60))
    notifier(f"bot sin latido hace {mins} min: "
             f"{canceled}/{len(orders)} ordenes en reposo canceladas")
    with open(latch_path, "w") as f:
        f.write(str(int(now)))
    return "acted"


def main() -> None:
    from hlbot.config import Config
    from hlbot.hl_client import HLClient
    result = check_once(lambda: HLClient(Config.from_env()), time.time())
    print(f"[watchdog] {result}", flush=True)


if __name__ == "__main__":
    main()
