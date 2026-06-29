from __future__ import annotations


def summarize_positions(clearinghouse_state: dict) -> list[dict]:
    out: list[dict] = []
    for ap in clearinghouse_state.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        liq = p.get("liquidationPx")
        out.append({
            "coin": p.get("coin"),
            "side": "long" if szi > 0 else "short",
            "leverage": (p.get("leverage", {}) or {}).get("value"),
            "notional": float(p.get("positionValue", 0) or 0),
            "size": abs(szi),
            "entry_px": float(p.get("entryPx", 0) or 0),
            "mark_px": None,  # el frontend usa el mid vivo del snapshot/ws
            "unrealized_pnl": float(p.get("unrealizedPnl", 0) or 0),
            "liq_px": float(liq) if liq not in (None, "") else None,
        })
    return out


def compose_account(clearinghouse_state: dict, fills: list[dict], funding_total: float,
                    session_start_value: float, max_open: int) -> dict:
    positions = summarize_positions(clearinghouse_state)
    equity = float((clearinghouse_state.get("marginSummary") or {}).get("accountValue", 0) or 0)
    unrealized = sum(p["unrealized_pnl"] for p in positions)
    closes = [f for f in fills if "Close" in (f.get("dir") or "")]
    realized = sum(float(f.get("closedPnl", 0) or 0) for f in closes)
    fees_paid = sum(float(f.get("fee", 0) or 0) for f in fills)
    wins = sum(1 for f in closes if float(f.get("closedPnl", 0) or 0) > 0)
    win_rate = (wins / len(closes)) if closes else 0.0
    return {
        "equity": equity,
        "session_pnl": equity - session_start_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "win_rate": win_rate,
        "fees_paid": fees_paid,
        "funding": funding_total,
        "open_count": len(positions),
        "max_open": max_open,
        "positions": positions,
    }


def merge_tape(decisions: list[dict], fills: list[dict], limit: int = 50) -> list[dict]:
    events: list[dict] = []
    for d in decisions:
        events.append({
            "ts": int(d.get("ts", 0)),
            "kind": "decision",
            "coin": d.get("coin"),
            "side": None,
            "price": None,
            "pnl": None,
            "reason": d.get("reason", ""),
        })
    for f in fills:
        dir_ = f.get("dir") or ""
        events.append({
            "ts": int(f.get("time", 0) or 0) // 1000,   # HL time viene en ms -> segundos
            "kind": "close" if "Close" in dir_ else "open",
            "coin": f.get("coin"),
            "side": "short" if "Short" in dir_ else ("long" if "Long" in dir_ else None),
            "price": float(f.get("px", 0) or 0),
            "pnl": float(f.get("closedPnl", 0) or 0) if "Close" in dir_ else None,
            "reason": dir_,
        })
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]


def format_candles(raw: list[dict]) -> list[dict]:
    out = [{
        "time": int(c.get("t", 0) or 0) // 1000,
        "open": float(c.get("o", 0) or 0), "high": float(c.get("h", 0) or 0),
        "low": float(c.get("l", 0) or 0), "close": float(c.get("c", 0) or 0),
    } for c in raw]
    out.sort(key=lambda c: c["time"])
    return out
