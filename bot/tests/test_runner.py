from hlbot.main import candles_to_models, build_market_state, refresh_account_cache
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


class _AcctClient:
    def user_state(self):
        return {"marginSummary": {"accountValue": "49.16"},
                "assetPositions": [{"position": {"coin": "BTC", "szi": "0.0002",
                    "entryPx": "67000", "positionValue": "12.4", "unrealizedPnl": "0.07",
                    "leverage": {"value": 3}, "liquidationPx": "47200"}}]}
    def user_fills(self):
        return [{"coin": "BTC", "time": 1, "dir": "Close Long", "px": "67550",
                 "closedPnl": "0.02", "fee": "0.0015"}]
    def user_funding(self, start_ms):
        return [{"delta": {"usdc": "0.001"}}, {"delta": {"usdc": "-0.0005"}}]

class _Eng:
    session_start_value = 50.0
    session_started_at = 0
    class cfg:
        class limits:
            max_open_positions = 4

def test_refresh_account_cache_populates():
    cache = refresh_account_cache(_AcctClient(), _Eng(), {}, fetch_extras=True)
    assert cache["equity"] == 49.16
    assert cache["open_count"] == 1
    assert abs(cache["funding"] - (0.001 - 0.0005)) < 1e-9
    assert cache["_fills"][0]["coin"] == "BTC"

def test_refresh_account_cache_preserves_fills_without_extras():
    c1 = refresh_account_cache(_AcctClient(), _Eng(), {}, fetch_extras=True)
    c2 = refresh_account_cache(_AcctClient(), _Eng(), c1, fetch_extras=False)
    assert c2["_fills"] == c1["_fills"]   # preservadas sin re-fetch
    assert c2["equity"] == 49.16
