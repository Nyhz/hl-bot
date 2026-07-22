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
    # funding positivo (largos pagan) -> objetivo corto -> referencia < mid (vende cerca del mid, acumula corto, cobra funding)
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0, funding=0.001)
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) < ms.mid

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


# ---------- A-S v2: microestructura (F2) ----------

def test_v1_parity_without_microstructure():
    # sin campos micro (backtest / WS caído) el grid v2 = v1 exacto:
    # fair=mid, sigma=ATR, sin término OFI
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.005)
    assert ms.microprice is None and ms.flow_ratio is None
    sigma = g._sigma(ms)
    cap = g.cfg.limits.max_coin_notional
    phi = max(-1.0, min(1.0, ms.inventory * ms.mid / cap))
    expected = ms.mid - phi * g.cfg.skew_strength * sigma
    assert abs(g.reservation_price(ms, sigma) - expected) < 1e-9


def test_fair_blends_mid_and_microprice():
    g = GridStrategy(_cfg())
    ms = _ms()
    ms.microprice = 3010.0                     # bbo cargado hacia arriba
    fair = g._fair(ms)
    assert 3000.0 < fair < 3010.0
    assert abs(fair - (0.7 * 3000.0 + 0.3 * 3010.0)) < 1e-9   # w=0.3 default


def test_sigma_prefers_realized_over_atr():
    g = GridStrategy(_cfg())
    ms = _ms(vol=10.0)                          # ATR ~ 10-20
    ms.sigma_px = 3.5
    assert g._sigma(ms) == 3.5
    ms.sigma_px = None
    assert g._sigma(ms) > 3.5                   # fallback ATR


def test_ofi_shifts_reservation_with_flow():
    g = GridStrategy(_cfg())
    base = _ms(inventory=0.0)
    sigma = g._sigma(base)
    res0 = g.reservation_price(base, sigma)
    buy = _ms(inventory=0.0)
    buy.flow_ratio = 0.8                        # presión compradora
    assert g.reservation_price(buy, sigma) > res0
    sell = _ms(inventory=0.0)
    sell.flow_ratio = -0.8
    assert g.reservation_price(sell, sigma) < res0


def test_too_toxic_requires_ratio_and_volume():
    g = GridStrategy(_cfg())
    ms = _ms()
    assert g.too_toxic(ms) is False             # sin tape
    ms.flow_ratio = 0.9
    ms.flow_total_usd = 1000.0                  # volumen de juguete: ignorar
    assert g.too_toxic(ms) is False
    ms.flow_total_usd = 50000.0
    assert g.too_toxic(ms) is True              # unidireccional Y con volumen
    ms.flow_ratio = -0.9
    assert g.too_toxic(ms) is True              # también en dirección vendedora
    ms.flow_ratio = 0.3
    assert g.too_toxic(ms) is False             # flujo mixto: cotizar normal


# ---------- F5: vol-sizing del rung ----------

def test_rung_notional_fixed_when_disabled():
    g = GridStrategy(_cfg())                            # risk_per_rung_usd=0
    ms = _ms()
    assert g._rung_notional(ms, sigma=50.0) == 10.0     # tamaño fijo v1


def test_rung_notional_scales_inverse_to_vol():
    limits = RiskLimits(40.0, 4, 2.0, 5.0, 20.0, 120.0)  # cap por posición $40
    cfg = SessionConfig(watchlist=["ETH"], capital=200.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02, risk_per_rung_usd=0.05)
    g = GridStrategy(cfg)
    ms = _ms(mid=3000.0)
    calm = g._rung_notional(ms, sigma=3.0)               # sigma_frac=0.1% -> 0.05/0.001=50 -> cap 40
    wild = g._rung_notional(ms, sigma=30.0)              # 1% -> $5 -> suelo $10
    assert calm == 40.0
    assert wild == 10.0
    mid_vol = g._rung_notional(ms, sigma=7.5)            # 0.25% -> $20
    assert abs(mid_vol - 20.0) < 1e-9


def test_too_toxic_relative_threshold():
    # Gate v2: el volumen exigido escala con la EWMA del propio coin — una
    # cascada es flujo anómalo para SU hora, no un número fijo de USD.
    g = GridStrategy(_cfg(toxicity_flow_ratio=0.85, toxicity_min_usd=100_000.0,
                          toxicity_rel_mult=3.0))
    ms = _ms()
    ms.flow_ratio = 0.95
    ms.flow_total_usd = 400_000.0
    ms.flow_ewma_usd = 200_000.0
    assert g.too_toxic(ms) is False              # 400k < 3×200k: hora punta normal
    ms.flow_total_usd = 700_000.0
    assert g.too_toxic(ms) is True               # 700k ≥ 600k: anómalo de verdad
    ms.flow_ewma_usd = None                      # EWMA fría (arranque): cae al suelo absoluto
    ms.flow_total_usd = 150_000.0
    assert g.too_toxic(ms) is True
    ms.flow_total_usd = 50_000.0
    assert g.too_toxic(ms) is False
