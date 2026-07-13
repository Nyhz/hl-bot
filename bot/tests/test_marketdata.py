import time

from hlbot.marketdata import MarketData, MAX_AGE_S, RESTART_AFTER_S


def _md(coins=("ETH",)):
    return MarketData("https://example", list(coins))   # sin start(): sin red


def _bbo_msg(coin="ETH", bid="3000", bsz="10", ask="3002", asz="2"):
    return {"data": {"coin": coin, "bbo": [{"px": bid, "sz": bsz},
                                           {"px": ask, "sz": asz}]}}


def test_bbo_and_mid_and_microprice():
    md = _md()
    md._on_bbo(_bbo_msg())
    b = md.bbo("ETH")
    assert b["bid_px"] == 3000.0 and b["ask_sz"] == 2.0
    assert md.mid("ETH") == 3001.0
    # bid 5x más grueso -> el precio justo se acerca al ask
    micro = md.microprice("ETH")
    assert 3001.0 < micro < 3002.0


def test_stale_bbo_returns_none():
    md = _md()
    md._on_bbo(_bbo_msg())
    md._bbo["ETH"]["ts"] = time.time() - MAX_AGE_S - 1
    assert md.bbo("ETH") is None
    assert md.mid("ETH") is None
    assert md.microprice("ETH") is None
    assert md.sigma_px("ETH") is None       # sigma exige bbo fresco


def test_sigma_needs_two_updates_then_positive():
    md = _md()
    md._on_bbo(_bbo_msg())
    assert md.sigma_px("ETH") is None        # una sola observación: sin retornos
    md._on_bbo(_bbo_msg(bid="3010", ask="3012"))
    s = md.sigma_px("ETH", horizon_s=60.0)
    assert s is not None and s > 0
    # proyección por horizonte: 4x tiempo -> 2x sigma
    assert abs(md.sigma_px("ETH", 240.0) / s - 2.0) < 1e-9


def test_flow_signed_and_window_eviction():
    md = _md()
    md._on_trades({"data": [
        {"coin": "ETH", "px": "3000", "sz": "2", "side": "B"},     # +6000
        {"coin": "ETH", "px": "3000", "sz": "1", "side": "A"},     # -3000
    ]})
    signed, total = md.flow("ETH", window_s=15.0)
    assert signed == 3000.0 and total == 9000.0
    # trades fuera de ventana no cuentan
    md._tape["ETH"][0] = (time.time() - 100, md._tape["ETH"][0][1])
    signed2, total2 = md.flow("ETH", window_s=15.0)
    assert signed2 == -3000.0 and total2 == 3000.0


def test_flow_ignores_unknown_coin():
    md = _md()
    md._on_trades({"data": [{"coin": "PEPE", "px": "1", "sz": "1", "side": "B"}]})
    assert md.flow("PEPE") == (0.0, 0.0)
    assert md.flow("ETH") == (0.0, 0.0)


def test_ensure_alive_reconnects_when_silent(monkeypatch):
    md = _md()
    calls = []
    monkeypatch.setattr(md, "_connect", lambda: calls.append(1))
    monkeypatch.setattr(md, "stop", lambda: None)
    md._last_msg_ts = time.time() - RESTART_AFTER_S - 1
    md._last_restart = time.time() - RESTART_AFTER_S - 1
    md.ensure_alive()
    assert calls == [1]
    # throttle: reintento inmediato NO reconecta otra vez
    md._last_restart = time.time()
    md._last_msg_ts = time.time() - RESTART_AFTER_S - 1
    md.ensure_alive()
    assert calls == [1]


def test_ensure_alive_quiet_when_fresh(monkeypatch):
    md = _md()
    monkeypatch.setattr(md, "_connect", lambda: (_ for _ in ()).throw(AssertionError))
    md._last_msg_ts = time.time()
    md.ensure_alive()                        # no toca nada


def test_malformed_bbo_does_not_poison_cache():
    md = _md()
    md._on_bbo({"data": {"coin": "ETH", "bbo": [None, None]}})
    assert md.bbo("ETH") is None
    md._on_bbo({"data": {}})
    md._on_bbo(_bbo_msg())                   # y después funciona normal
    assert md.mid("ETH") == 3001.0
