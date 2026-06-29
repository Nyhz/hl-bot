from hlbot.main import candles_to_models, build_market_state
from hlbot.models import Candle

RAW = [{"t": 1, "o": "10", "h": "12", "l": "9", "c": "11", "v": "100"},
       {"t": 2, "o": "11", "h": "13", "l": "10", "c": "12", "v": "120"}]

def test_candles_to_models_maps_fields():
    cs = candles_to_models(RAW)
    assert len(cs) == 2
    assert isinstance(cs[0], Candle)
    assert cs[0].open == 10.0 and cs[0].high == 12.0 and cs[0].close == 11.0
    assert cs[1].t == 2

class _FakeClient:
    def mid(self, coin): return 11.5
    def candles(self, coin, interval, start, end): return RAW

def test_build_market_state():
    ms, raw = build_market_state(_FakeClient(), "ETH", now_ms=999)
    assert ms.coin == "ETH" and ms.mid == 11.5
    assert len(ms.candles) == 2
    assert raw is RAW
