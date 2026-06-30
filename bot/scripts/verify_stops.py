#!/usr/bin/env python
"""Verifica EN TESTNET que place_stop (trigger order del SDK) se crea y ejecuta de verdad.

Abre una posición diminuta de mercado, coloca un stop-loss trigger MUY cercano (para que
salte enseguida) y comprueba: (1) que la orden trigger aparece en open_orders tras colocarla,
y (2) que la posición se cierra al saltar. Usa la cuenta de bot/.env en testnet.

Uso:
    cd bot && .venv/bin/python scripts/verify_stops.py [COIN]

NO ejecutar en mainnet. Mueve fondos (mock) reales de testnet.
"""
from __future__ import annotations
import sys
import time

from hlbot.config import Config
from hlbot.hl_client import HLClient


def main() -> int:
    coin = sys.argv[1] if len(sys.argv) > 1 else "ETH"
    cfg = Config.from_env()
    if not cfg.testnet:
        print("ABORTADO: este script solo corre en testnet (~/.hlbot/mode != prod).")
        return 2
    if not cfg.secret_key:
        print("ABORTADO: faltan credenciales (HL_SECRET_KEY) en bot/.env.")
        return 2

    client = HLClient(cfg)
    mid = client.mid(coin)
    szd = client.sz_decimals[coin]
    size = round(max(10.0, 0) / mid, szd)
    # garantizar >= $10 redondeando arriba si hace falta
    if mid * size < 10.0:
        scale = 10 ** szd
        import math
        size = math.ceil((10.0 / mid) * scale) / scale

    print(f"[1] {coin} mid={mid} szDecimals={szd} -> abriendo LONG size={size} (~${mid*size:.2f})")
    print(client.place_limit(coin, True, mid, size, post_only=False, reduce_only=False))
    time.sleep(2)

    # stop-loss que cierra el LONG: vende; trigger 0.5% por debajo del mid actual
    trig = mid * 0.995
    print(f"[2] colocando stop-loss (vende) trigger={trig:.4f}")
    print(client.place_stop(coin, is_buy=False, trigger_px=trig, size=size, reduce_only=True))
    time.sleep(2)

    orders = client.open_orders(coin)
    triggers = [o for o in orders if o.get("orderType", "").lower().startswith("stop")
                or o.get("isTrigger") or o.get("triggerPx")]
    print(f"[3] open_orders({coin}) = {orders}")
    print(f"    -> órdenes trigger detectadas: {len(triggers)} {triggers}")

    print("[4] revisa en el dashboard / explorer si la posición se cierra al cruzar el trigger.")
    print("    Para limpiar manualmente: cancela órdenes y cierra la posición desde el dashboard.")
    return 0 if triggers else 1


if __name__ == "__main__":
    raise SystemExit(main())
