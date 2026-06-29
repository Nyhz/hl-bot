from __future__ import annotations


def session_summary(session_row: dict, fills: list[dict], funding: list[dict],
                    pnl_snapshots: list[dict]) -> dict:
    closes = [f for f in fills if "Close" in (f.get("dir") or "")]
    realized = sum(float(f.get("closed_pnl") or 0) for f in closes)
    fees = sum(float(f.get("fee") or 0) for f in fills)
    fund = sum(float(f.get("amount") or 0) for f in funding)
    wins = sum(1 for f in closes if float(f.get("closed_pnl") or 0) > 0)
    win_rate = (wins / len(closes)) if closes else 0.0
    net_pnl = float(pnl_snapshots[-1]["total_pnl"]) if pnl_snapshots else 0.0
    started = session_row.get("started_at")
    ended = session_row.get("ended_at")
    duration = (ended - started) if (started and ended) else None
    return {
        "id": session_row.get("id"),
        "mode": session_row.get("mode"),
        "started_at": started,
        "ended_at": ended,
        "duration_s": duration,
        "capital": session_row.get("capital"),
        "n_trades": len(closes),
        "wins": wins,
        "realized_pnl": realized,
        "fees": fees,
        "funding": fund,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
    }


def global_stats(summaries: list[dict]) -> dict:
    out: dict = {}
    for mode in ("testnet", "mainnet"):
        ms = [s for s in summaries if s.get("mode") == mode]
        trades = sum(s.get("n_trades", 0) for s in ms)
        wins = sum(s.get("wins", 0) for s in ms)
        best = max(ms, key=lambda s: s.get("net_pnl", 0), default=None)
        worst = min(ms, key=lambda s: s.get("net_pnl", 0), default=None)
        out[mode] = {
            "n_sessions": len(ms),
            "realized_pnl": sum(s.get("realized_pnl", 0) for s in ms),
            "fees": sum(s.get("fees", 0) for s in ms),
            "funding": sum(s.get("funding", 0) for s in ms),
            "net_pnl": sum(s.get("net_pnl", 0) for s in ms),
            "win_rate": (wins / trades) if trades else 0.0,
            "best_session": best["id"] if best else None,
            "worst_session": worst["id"] if worst else None,
        }
    return out
