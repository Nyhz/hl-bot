from hlbot.models import Candle, RiskLimits, SessionConfig
from hlbot.backtest.runner import run_backtest
from hlbot.backtest.metrics import compute_metrics

def _cfg():
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)
    return SessionConfig(watchlist=["ETH"], capital=1000.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def _oscillating(n=120, base=3000.0, amp=30.0):
    # sube y baja en rango para que el grid cace ambos lados
    import math
    out = []
    for i in range(1, n + 1):
        c = base + amp * math.sin(i / 5.0)
        out.append(Candle(t=i * 60000, open=c, high=c + 5, low=c - 5, close=c, volume=1.0))
    return out

def test_run_backtest_returns_structure_and_runs_engine():
    res = run_backtest("ETH", _oscillating(), [], _cfg(), {"ETH": 4})
    assert set(res) == {"metrics", "equity_curve", "trades", "decisions"}
    assert len(res["equity_curve"]) > 0
    assert "net_pnl" in res["metrics"]
    # en un rango oscilante el grid debe haber colocado/llenado algo
    assert res["metrics"]["n_trades"] >= 0

def test_compute_metrics_drawdown_and_net():
    curve = [{"ts": 1, "total_pnl": 1000.0}, {"ts": 2, "total_pnl": 1010.0},
             {"ts": 3, "total_pnl": 990.0}, {"ts": 4, "total_pnl": 1005.0}]
    m = compute_metrics(curve, fills=[
        {"dir": "Close Long", "closed_pnl": 5.0, "fee": 0.1},
        {"dir": "Close Long", "closed_pnl": -3.0, "fee": 0.1},
        {"dir": "Open Long", "closed_pnl": 0.0, "fee": 0.1},
    ], funding_total=-0.5)
    assert m["start_equity"] == 1000.0 and m["final_equity"] == 1005.0
    assert abs(m["net_pnl"] - 5.0) < 1e-9            # 1005 - 1000
    assert m["n_trades"] == 2                         # solo cierres cuentan como trade
    assert abs(m["win_rate"] - 0.5) < 1e-9           # 1 de 2 cierres positivo
    assert abs(m["max_drawdown"] - 20.0) < 1e-9      # 1010 -> 990
