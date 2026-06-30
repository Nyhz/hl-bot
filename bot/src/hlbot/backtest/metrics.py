from __future__ import annotations


def compute_metrics(equity_curve: list[dict], fills: list[dict], funding_total: float) -> dict:
    start = equity_curve[0]["total_pnl"] if equity_curve else 0.0
    final = equity_curve[-1]["total_pnl"] if equity_curve else start
    closes = [f for f in fills if "Close" in f["dir"]]
    realized = sum(f["closed_pnl"] for f in closes)
    fees = sum(f["fee"] for f in fills)
    wins = sum(1 for f in closes if f["closed_pnl"] > 0)
    peak = start
    max_dd = 0.0
    for p in equity_curve:
        peak = max(peak, p["total_pnl"])
        max_dd = max(max_dd, peak - p["total_pnl"])
    return {
        "start_equity": start, "final_equity": final, "net_pnl": final - start,
        "realized_pnl": realized, "fees": fees, "funding": funding_total,
        "n_trades": len(closes), "win_rate": (wins / len(closes)) if closes else 0.0,
        "max_drawdown": max_dd,
    }
