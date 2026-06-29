from hlbot.account import summarize_positions, compose_account, merge_tape, format_candles

CH = {
    "marginSummary": {"accountValue": "49.16"},
    "assetPositions": [
        {"position": {"coin": "BTC", "szi": "0.0002", "entryPx": "67000",
                      "positionValue": "12.40", "unrealizedPnl": "0.07",
                      "leverage": {"value": 3}, "liquidationPx": "47200.9"}},
        {"position": {"coin": "ETH", "szi": "-0.003", "entryPx": "3121",
                      "positionValue": "10.10", "unrealizedPnl": "-0.27",
                      "leverage": {"value": 2}, "liquidationPx": "4525.9"}},
    ],
}
FILLS = [
    {"coin": "BTC", "time": 1000, "dir": "Close Long", "px": "67550",
     "closedPnl": "0.02", "fee": "0.0015"},
    {"coin": "SOL", "time": 900, "dir": "Close Short", "px": "150",
     "closedPnl": "-0.17", "fee": "0.0009"},
]

def test_summarize_positions_side_and_fields():
    pos = summarize_positions(CH)
    assert len(pos) == 2
    btc = next(p for p in pos if p["coin"] == "BTC")
    assert btc["side"] == "long" and btc["leverage"] == 3
    eth = next(p for p in pos if p["coin"] == "ETH")
    assert eth["side"] == "short"
    assert btc["unrealized_pnl"] == 0.07 and btc["notional"] == 12.40

def test_compose_account():
    acc = compose_account(CH, FILLS, funding_total=0.002,
                          session_start_value=50.0, max_open=4)
    assert acc["equity"] == 49.16
    assert abs(acc["session_pnl"] - (49.16 - 50.0)) < 1e-9
    assert abs(acc["realized_pnl"] - (0.02 - 0.17)) < 1e-9     # suma closedPnl
    assert abs(acc["fees_paid"] - (0.0015 + 0.0009)) < 1e-9
    assert acc["funding"] == 0.002
    assert acc["open_count"] == 2 and acc["max_open"] == 4
    # win rate: 1 ganador (0.02) de 2 cierres = 0.5
    assert abs(acc["win_rate"] - 0.5) < 1e-9
    assert abs(acc["unrealized_pnl"] - (0.07 - 0.27)) < 1e-9
    assert len(acc["positions"]) == 2

def test_merge_tape_orders_desc_and_classifies():
    decisions = [{"ts": 1700000950, "coin": "BTC", "action": "place_limit", "reason": "grid rung"}]
    fills = [
        {"coin": "BTC", "time": 1700001000000, "dir": "Close Long", "px": "67550",
         "closedPnl": "0.02", "fee": "0.0015"},   # 1700001000 s
        {"coin": "SOL", "time": 1700000900000, "dir": "Close Short", "px": "150",
         "closedPnl": "-0.17", "fee": "0.0009"},   # 1700000900 s
    ]
    tape = merge_tape(decisions, fills, limit=10)
    assert [e["ts"] for e in tape] == [1700001000, 1700000950, 1700000900]  # desc, en segundos
    close = next(e for e in tape if e["coin"] == "BTC" and e["kind"] == "close")
    assert close["ts"] == 1700001000 and close["pnl"] == 0.02
    dec = next(e for e in tape if e["kind"] == "decision")
    assert dec["ts"] == 1700000950 and dec["reason"] == "grid rung"

def test_format_candles_to_seconds_ascending():
    raw = [{"t": 60000, "o": "10", "h": "12", "l": "9", "c": "11", "v": "1"},
           {"t": 120000, "o": "11", "h": "13", "l": "10", "c": "12", "v": "1"}]
    out = format_candles(raw)
    assert out[0] == {"time": 60, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}
    assert out[1]["time"] == 120

def test_summarize_positions_skips_zero_szi():
    ch = {"marginSummary": {"accountValue": "10"},
          "assetPositions": [
              {"position": {"coin": "BTC", "szi": "0", "entryPx": "1", "positionValue": "0",
                            "unrealizedPnl": "0", "leverage": {"value": 1}, "liquidationPx": None}},
              {"position": {"coin": "ETH", "szi": "0.5", "entryPx": "3000", "positionValue": "10",
                            "unrealizedPnl": "0.1", "leverage": {"value": 2}, "liquidationPx": "2000"}},
          ]}
    pos = summarize_positions(ch)
    assert [p["coin"] for p in pos] == ["ETH"]  # BTC con szi=0 se omite
