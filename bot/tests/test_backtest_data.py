from hlbot.backtest.data import funding_at, candles_from_raw

def test_funding_at_picks_last_le_ts():
    rows = [{"time": 0, "fundingRate": 0.0001},
            {"time": 3600000, "fundingRate": 0.0002},
            {"time": 7200000, "fundingRate": -0.0001}]
    assert funding_at(rows, 0) == 0.0001
    assert funding_at(rows, 5000000) == 0.0002       # entre 1h y 2h
    assert funding_at(rows, 10000000) == -0.0001
    assert funding_at(rows, -1) is None              # antes del primero

def test_candles_from_raw_normalizes_and_sorts():
    raw = [{"t": 120000, "o": "2", "h": "3", "l": "1", "c": "2", "v": "1"},
           {"t": 60000, "o": "1", "h": "2", "l": "1", "c": "1.5", "v": "1"}]
    cs = candles_from_raw(raw)
    assert [c.t for c in cs] == [60000, 120000]
    assert cs[0].close == 1.5
