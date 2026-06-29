from hlbot.track_record import session_summary, global_stats

SESS = {"id": 1, "mode": "testnet", "started_at": 1000, "ended_at": 1600, "capital": 40.0}
FILLS = [
    {"dir": "Close Long", "closed_pnl": 0.05, "fee": 0.0015},
    {"dir": "Close Short", "closed_pnl": -0.02, "fee": 0.0010},
    {"dir": "Open Long", "closed_pnl": 0.0, "fee": 0.0012},
]
FUND = [{"amount": -0.001}, {"amount": 0.0003}]
SNAPS = [{"ts": 1100, "total_pnl": 0.01}, {"ts": 1500, "total_pnl": 0.03}]

def test_session_summary():
    s = session_summary(SESS, FILLS, FUND, SNAPS)
    assert s["id"] == 1 and s["mode"] == "testnet"
    assert s["duration_s"] == 600
    assert s["n_trades"] == 2                       # solo "Close"
    assert s["wins"] == 1
    assert abs(s["realized_pnl"] - 0.03) < 1e-9     # 0.05 - 0.02
    assert abs(s["fees"] - (0.0015 + 0.0010 + 0.0012)) < 1e-9
    assert abs(s["funding"] - (-0.001 + 0.0003)) < 1e-9
    assert abs(s["win_rate"] - 0.5) < 1e-9
    assert abs(s["net_pnl"] - 0.02) < 1e-9     # equity final - inicial = 0.03 - 0.01

def test_session_summary_no_data():
    s = session_summary({"id": 2, "mode": "mainnet", "started_at": 1, "ended_at": None,
                         "capital": 50.0}, [], [], [])
    assert s["n_trades"] == 0 and s["win_rate"] == 0.0
    assert s["net_pnl"] == 0.0 and s["duration_s"] is None

def test_session_summary_net_pnl_is_equity_delta():
    snaps = [{"ts": 1, "total_pnl": 50.0}, {"ts": 2, "total_pnl": 50.4}]
    s = session_summary({"id": 1, "mode": "testnet", "started_at": 1, "ended_at": 2,
                         "capital": 50.0}, [], [], snaps)
    assert abs(s["net_pnl"] - 0.4) < 1e-9      # 50.4 - 50.0

def test_global_stats_separates_modes():
    summaries = [
        {"mode": "testnet", "n_trades": 2, "wins": 1, "realized_pnl": 0.03, "fees": 0.004,
         "funding": -0.001, "net_pnl": 0.02, "id": 1},
        {"mode": "testnet", "n_trades": 1, "wins": 1, "realized_pnl": 0.10, "fees": 0.001,
         "funding": 0.0, "net_pnl": 0.09, "id": 2},
        {"mode": "mainnet", "n_trades": 1, "wins": 0, "realized_pnl": -0.05, "fees": 0.001,
         "funding": 0.0, "net_pnl": -0.06, "id": 3},
    ]
    g = global_stats(summaries)
    assert g["testnet"]["n_sessions"] == 2
    assert abs(g["testnet"]["realized_pnl"] - 0.13) < 1e-9
    assert abs(g["testnet"]["win_rate"] - (2/3)) < 1e-9   # 2 wins / 3 trades
    assert g["testnet"]["best_session"] == 2 and g["testnet"]["worst_session"] == 1
    assert g["mainnet"]["n_sessions"] == 1
    assert abs(g["mainnet"]["realized_pnl"] - (-0.05)) < 1e-9
