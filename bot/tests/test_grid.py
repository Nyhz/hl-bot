from hlbot.models import MarketState, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.grid import GridStrategy

def _cfg():
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0)
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
    # cada rung tiene el notional de la posición configurada (max_position_notional = $10)
    assert all(abs(d.price * d.size - 10.0) < 1e-6 for d in decisions)

def test_evaluate_range_exit_when_price_above_upper():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3100.0)  # por encima de upper=3060
    decisions = g.evaluate(ms)
    assert len(decisions) == 1
    assert decisions[0].action == ActionType.CLOSE
    assert decisions[0].reduce_only is True

def test_conditions_expose_both_bounds():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3000.0)
    conds = g.conditions(ms)
    names = {c.name for c in conds}
    assert names == {"precio_sobre_limite_inferior", "precio_bajo_limite_superior"}
    assert all(c.met for c in conds)  # en rango -> ambas cumplidas
    # cada condicion es internamente consistente (value vs threshold coincide con met)
    lower_c = next(c for c in conds if c.name == "precio_sobre_limite_inferior")
    assert (lower_c.value >= lower_c.threshold) == lower_c.met
