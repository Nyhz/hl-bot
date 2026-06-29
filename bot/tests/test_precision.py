from hlbot.hl_client import round_size, round_price, meets_min_notional


def test_round_size_to_decimals():
    assert round_size(0.123456, 3) == 0.123


def test_round_price_decimals_limit():
    # perp con szDecimals=1 -> max 6-1=5 decimales
    assert round_price(1234.567891, sz_decimals=1) == 1234.6  # 5 sig figs


def test_round_price_five_sig_figs():
    assert round_price(0.123456, sz_decimals=2) == 0.12346


def test_min_notional_above_threshold_is_true():
    assert meets_min_notional(3000.0, 0.004) is True   # 12.0 >= 10


def test_min_notional_below_threshold_is_false():
    assert meets_min_notional(3000.0, 0.003) is False  # 9.0 < 10
