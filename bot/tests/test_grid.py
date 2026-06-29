from hlbot.models import MarketState, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.grid import GridStrategy

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def test_anchor_sets_symmetric_bounds():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    assert abs(g.lower - 2940.0) < 1e-6
    assert abs(g.upper - 3060.0) < 1e-6
    assert len(g.levels) == 5  # grid_n + 1

def test_triggers_buys_below_sells_above():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3000.0)
    trs = g.armed_triggers(ms)
    buys = [t for t in trs if t.side == Side.BUY]
    sells = [t for t in trs if t.side == Side.SELL]
    assert all(t.level < 3000.0 for t in buys)
    assert all(t.level > 3000.0 for t in sells)

def test_evaluate_range_exit_when_price_below_lower():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=2900.0)  # por debajo de lower=2940
    decisions = g.evaluate(ms)
    assert len(decisions) == 1
    assert decisions[0].action == ActionType.CLOSE
    assert decisions[0].reduce_only is True

def test_evaluate_places_maker_orders_in_range():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3000.0)
    decisions = g.evaluate(ms)
    assert all(d.action == ActionType.PLACE_LIMIT for d in decisions)
    assert all(d.price * d.size >= 10.0 for d in decisions)  # min notional
