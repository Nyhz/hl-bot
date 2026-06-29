import math
from hlbot.indicators import ema, atr, adx

def test_ema_of_constant_is_constant():
    assert all(abs(x - 5.0) < 1e-9 for x in ema([5.0] * 10, 3))

def test_ema_known_values():
    # span=2 -> alpha=2/3; e0=1, e1=1.6667, e2=2.5556
    out = ema([1.0, 2.0, 3.0], 2)
    assert abs(out[0] - 1.0) < 1e-6
    assert abs(out[1] - 1.66667) < 1e-4
    assert abs(out[2] - 2.55556) < 1e-4

def test_atr_is_positive():
    highs = [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20]
    lows = [9, 10, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 16, 18, 19]
    closes = [9.5, 10.5, 11.5, 10.5, 12.5, 13.5, 12.5, 14.5, 15.5, 14.5, 16.5, 17.5, 16.5, 18.5, 19.5]
    out = atr(highs, lows, closes, 14)
    assert out[-1] > 0

def test_adx_in_range_and_high_in_strong_trend():
    # tendencia alcista fuerte -> ADX alto
    closes = [float(i) for i in range(1, 41)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    out = adx(highs, lows, closes, 14)
    last = out[-1]
    assert 0.0 <= last <= 100.0
    assert last > 25.0  # mercado en tendencia clara
