from hlbot.hl_client import round_size, round_price, meets_min_notional


def test_round_size_to_decimals():
    assert round_size(0.123456, 3) == 0.123


def test_round_price_decimals_limit():
    # perp con szDecimals=1 -> max 6-1=5 decimales
    assert round_price(1234.567891, sz_decimals=1) == 1234.6  # 5 sig figs


def test_round_price_five_sig_figs_capped_by_decimals():
    # szDecimals=2 -> max 4 decimales (6-2); 5 sig figs necesitarían 5, se capan a 4
    assert round_price(0.123456, sz_decimals=2) == 0.1235

def test_round_price_five_sig_figs_uncapped():
    # szDecimals=0 -> max 6 decimales; aquí mandan las 5 cifras significativas
    assert round_price(0.123456, sz_decimals=0) == 0.12346


def test_min_notional_above_threshold_is_true():
    assert meets_min_notional(3000.0, 0.004) is True   # 12.0 >= 10


def test_min_notional_below_threshold_is_false():
    assert meets_min_notional(3000.0, 0.003) is False  # 9.0 < 10


def test_stop_order_type_is_market_sl():
    from hlbot.hl_client import stop_order_type
    ot = stop_order_type(2940.0)
    assert ot["trigger"]["isMarket"] is True
    assert ot["trigger"]["tpsl"] == "sl"
    assert ot["trigger"]["triggerPx"] == 2940.0


def test_order_response_error_detects_status_error():
    from hlbot.hl_client import order_response_error
    resp = {"status": "ok", "response": {"data": {"statuses": [
        {"error": "Order could not immediately match against any resting orders"}]}}}
    err = order_response_error(resp)
    assert err is not None and "match" in err


def test_order_response_error_none_response_is_error():
    # market_close del SDK devuelve None si no ve la posición: no es un éxito
    from hlbot.hl_client import order_response_error
    assert order_response_error(None) is not None


def test_order_response_error_accepts_ok_responses():
    from hlbot.hl_client import order_response_error
    filled = {"status": "ok", "response": {"data": {"statuses": [
        {"filled": {"totalSz": "0.01", "avgPx": "3000", "oid": 7}}]}}}
    assert order_response_error(filled) is None
    assert order_response_error({"status": "ok"}) is None   # respuestas mínimas (fakes)


def test_order_response_error_err_status():
    from hlbot.hl_client import order_response_error
    assert order_response_error({"status": "err", "response": "rate limited"}) is not None


def test_order_response_errors_batch_alignment():
    from hlbot.hl_client import order_response_errors
    resp = {"status": "ok", "response": {"data": {"statuses": [
        {"resting": {"oid": 1}},
        {"error": "Post only order would have immediately matched"},
        {"resting": {"oid": 2}},
    ]}}}
    errs = order_response_errors(resp, 3)
    assert errs[0] is None and errs[2] is None
    assert "immediately matched" in errs[1]


def test_order_response_errors_toplevel_error_applies_to_all():
    from hlbot.hl_client import order_response_errors
    errs = order_response_errors({"status": "err", "response": "rate limited"}, 2)
    assert errs == ["rate limited", "rate limited"]
    assert order_response_errors(None, 2) == ["sin respuesta del SDK"] * 2
