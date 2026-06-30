from hlbot.models import MarketState, Candle, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.grid import GridStrategy

def _cfg(**kw):
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02, **kw)

def _candles(vol=10.0, n=40, base=3000.0):
    # velas con rango ~vol para que ATR ~ vol
    return [Candle(t=i, open=base, high=base + vol, low=base - vol, close=base, volume=1.0)
            for i in range(1, n + 1)]

def _ms(mid=3000.0, inventory=0.0, funding=None, vol=10.0):
    return MarketState(coin="ETH", mid=mid, candles=_candles(vol=vol), funding_rate=funding,
                       inventory=inventory)

def test_reservation_equals_mid_when_flat():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    sigma = g._sigma(ms)
    assert abs(g.reservation_price(ms, sigma) - ms.mid) < 1e-9

def test_reservation_below_mid_when_long():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.005)   # largo
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) < ms.mid

def test_reservation_above_mid_when_short():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=-0.005)
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) > ms.mid

def test_half_spread_grows_with_volatility():
    g = GridStrategy(_cfg())
    lo = g.half_spread(_ms(vol=5.0), g._sigma(_ms(vol=5.0)))
    hi = g.half_spread(_ms(vol=40.0), g._sigma(_ms(vol=40.0)))
    assert hi > lo

def test_funding_positive_targets_short_reservation():
    # funding positivo (largos pagan) y estando flat -> objetivo corto -> referencia > mid
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0, funding=0.001)
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) > ms.mid

def test_evaluate_rungs_are_ten_dollars_and_dont_cross_mid():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    ds = [d for d in g.evaluate(ms) if d.action == ActionType.PLACE_LIMIT]
    assert ds
    for d in ds:
        assert abs(d.price * d.size - 10.0) < 1e-6
        if d.side == Side.BUY:
            assert d.price < ms.mid
        else:
            assert d.price > ms.mid

def test_evaluate_emits_only_place_limit_rungs():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    ds = g.evaluate(ms)
    assert ds and all(d.action == ActionType.PLACE_LIMIT for d in ds)  # grid no cierra por precio
