from hlbot.backtest.broker import BacktestBroker
from hlbot.models import Candle

def _bk():
    b = BacktestBroker(capital=1000.0, sz_decimals={"ETH": 4})
    b.set_price("ETH", 3000.0); b.set_ts(1000)
    return b

def _candle(t, o, h, l, c):
    return Candle(t=t, open=o, high=h, low=l, close=c, volume=1.0)

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

def test_step_fills_buy_when_low_crosses():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True)
    b.step("ETH", _candle(60000, 3000, 3005, 2985, 2995), None)  # low 2985 <= 2990
    assert b.open_orders("ETH") == []                            # se llenó
    assert b.positions["ETH"]["size"] == 0.0034

def test_step_does_not_fill_when_not_crossed():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True)
    b.step("ETH", _candle(60000, 3000, 3010, 2995, 3005), None)  # low 2995 > 2990
    assert len(b.open_orders("ETH")) == 1

def test_step_stop_triggers_for_long():
    b = _bk()
    b.market_open("ETH", True, 0.01)                             # largo a 3000
    b.place_stop("ETH", False, 2940.0, 0.01, reduce_only=True)   # stop venta
    b.step("ETH", _candle(60000, 3000, 3000, 2930, 2935), None)  # low 2930 <= 2940
    assert b.positions["ETH"]["size"] == 0                       # cerrado por stop
    assert b.open_orders("ETH") == []

def test_step_applies_hourly_funding_long_pays_positive():
    b = _bk()
    b.market_open("ETH", True, 0.01)                             # largo notional ~30
    cash0 = b.cash
    b.set_ts(0)
    b.step("ETH", _candle(3600000, 3000, 3000, 3000, 3000), 0.0001)  # cruza 1 hora, funding +
    assert b.cash < cash0                                        # largo paga funding positivo
    assert b.funding_total < 0                                   # a long paying positive funding gives negative funding_total
