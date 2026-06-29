from hlbot.models import MarketState, Candle, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.trend import TrendOverlayStrategy

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits)

def _uptrend_candles(n=60):
    out = []
    for i in range(1, n + 1):
        c = float(i)
        out.append(Candle(t=i, open=c - 0.5, high=c + 0.5, low=c - 0.5, close=c, volume=1.0))
    return out

def _flat_candles(n=60):
    return [Candle(t=i, open=100.0, high=100.5, low=99.5, close=100.0, volume=1.0)
            for i in range(1, n + 1)]

def test_is_trending_true_in_strong_uptrend():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    assert s.is_trending(ms) is True

def test_is_trending_false_when_flat():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=100.0, candles=_flat_candles())
    assert s.is_trending(ms) is False

def test_evaluate_opens_long_with_stop_in_uptrend():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    decisions = s.evaluate(ms)
    actions = [d.action for d in decisions]
    assert ActionType.PLACE_MARKET in actions
    assert ActionType.SET_STOP in actions
    long_d = next(d for d in decisions if d.action == ActionType.PLACE_MARKET)
    assert long_d.side == Side.BUY

def test_conditions_expose_adx():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    names = [c.name for c in s.conditions(ms)]
    assert "adx" in names
