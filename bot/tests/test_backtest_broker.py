from hlbot.backtest.broker import BacktestBroker

def _bk():
    b = BacktestBroker(capital=1000.0, sz_decimals={"ETH": 4})
    b.set_price("ETH", 3000.0); b.set_ts(1000)
    return b

def test_place_limit_rests_with_oid():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True, reduce_only=False)
    oo = b.open_orders("ETH")
    assert len(oo) == 1 and oo[0]["limitPx"] == 2990.0 and "oid" in oo[0]

def test_market_open_takes_position_and_charges_taker_fee():
    b = _bk()
    b.market_open("ETH", True, 0.0034)            # ~$10.2 notional
    st = b.user_state()
    pos = st["assetPositions"][0]["position"]
    assert float(pos["szi"]) == 0.0034
    assert b.fees_total > 0                         # taker fee cobrada
    assert abs(b.cash - (1000.0 - b.fees_total)) < 1e-9  # abrir no mueve caja salvo fee

def test_market_close_realizes_pnl():
    b = _bk()
    b.market_open("ETH", True, 0.01)               # largo a 3000
    b.set_price("ETH", 3100.0)                      # +100
    b.market_close("ETH")
    assert b.positions.get("ETH", {"size": 0})["size"] == 0
    assert b.realized_total > 0                     # ganancia realizada (~+1.0 menos fees)
    closes = [f for f in b.fills if "Close" in f["dir"]]
    assert len(closes) == 1 and closes[0]["closed_pnl"] > 0

def test_user_state_equity_includes_unrealized():
    b = _bk()
    b.market_open("ETH", True, 0.01)               # largo a 3000
    b.set_price("ETH", 3100.0)
    eq = float(b.user_state()["marginSummary"]["accountValue"])
    assert eq > 1000.0                              # caja + no realizado (+1) - fees
