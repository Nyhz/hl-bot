from __future__ import annotations
import time
from hlbot.models import Candle

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def candles_from_raw(raw: list[dict]) -> list[Candle]:
    out = [Candle(t=int(c["t"]), open=float(c["o"]), high=float(c["h"]),
                  low=float(c["l"]), close=float(c["c"]), volume=float(c.get("v", 0) or 0))
           for c in raw]
    out.sort(key=lambda c: c.t)
    return out


def fetch_candles(client, coin: str, interval: str, n: int) -> list[Candle]:
    step = INTERVAL_MS.get(interval, 60_000)
    end = int(time.time() * 1000)
    start = end - step * min(n, 5000)
    raw = client.candles(coin, interval, start, end)
    return candles_from_raw(raw)


def fetch_funding(client, coin: str, start_ms: int) -> list[dict]:
    rows = client.info.funding_history(coin, start_ms)
    out = []
    for r in rows:
        out.append({"time": int(r.get("time", 0) or 0),
                    "fundingRate": float(r.get("fundingRate", 0) or 0)})
    out.sort(key=lambda r: r["time"])
    return out


def funding_at(funding_rows: list[dict], ts_ms: int) -> float | None:
    val = None
    for r in funding_rows:
        if r["time"] <= ts_ms:
            val = r["fundingRate"]
        else:
            break
    return val
