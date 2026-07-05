from hlbot.main import candles_to_models, build_market_state, refresh_account_cache
from hlbot.models import Candle
from hlbot.store import Store

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


def _run_cfg():
    from hlbot.models import RiskLimits, SessionConfig
    return SessionConfig(watchlist=[], capital=40.0,
                         limits=RiskLimits(10.0, 4, 2.0, 5.0, 20.0), grid_n=4, grid_range_pct=0.02)


def test_run_tick_executes_under_lock_and_releases():
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_run_cfg())                      # ver helper abajo
    shared = {}; cache = {"v": {}}; counters = {"loop": 0, "ticks": 0}
    run_tick(eng, eng.client, eng.store, shared, cache, counters)   # un tick, síncrono
    assert counters["loop"] == 1
    assert eng.lock.acquire(blocking=False) is True   # el lock quedó libre tras el tick
    eng.lock.release()


def test_run_tick_refreshes_cache_without_session():
    # tras kill/close (cfg=None) la caché debe seguir reflejando la cuenta real,
    # no quedarse congelada con las posiciones de antes del cierre (gráficos "abiertos")
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())     # sin sesión (cfg None)
    stale = {"positions": [{"coin": "ETH"}], "open_count": 1}
    cache = {"v": stale}
    run_tick(eng, eng.client, eng.store, {}, cache, {"loop": 0, "ticks": 0})
    assert cache["v"]["positions"] == []               # refrescada desde user_state real
    assert cache["v"]["open_count"] == 0


def test_refresh_account_cache_clears_session_data_without_session():
    class _EngNone:
        session_start_value = 0.0
        session_started_at = None
        session_id = None
        cfg = None
    prev = {"_fills": [{"coin": "BTC"}], "_funding": 1.23}
    cache = refresh_account_cache(_AcctClient(), _EngNone(), prev, fetch_extras=True)
    assert cache["_fills"] == []                       # fills de la sesión anterior fuera
    assert cache["session_pnl"] == 0.0                 # sin sesión no hay pnl de sesión


def test_refresh_records_fills_dedup(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["BTC"], 40.0, mode="testnet")

    class _Eng2:
        session_start_value = 50.0
        session_started_at = 0
        session_id = sid
        class cfg:
            class limits:
                max_open_positions = 4

    class _Client2:
        def user_state(self):
            return {"marginSummary": {"accountValue": "49"}, "assetPositions": []}
        def user_fills(self):
            return [{"tid": 7, "time": 1000, "coin": "BTC", "side": "B",
                     "dir": "Close Long", "px": "67550", "sz": "0.0002",
                     "fee": "0.0015", "closedPnl": "0.02"}]
        def user_funding(self, start_ms):
            return [{"time": 1000, "hash": "h1", "delta": {"usdc": "-0.001", "coin": "BTC"}}]

    c = _Client2()
    refresh_account_cache(c, _Eng2(), {}, fetch_extras=True, store=store)
    refresh_account_cache(c, _Eng2(), {}, fetch_extras=True, store=store)  # 2ª vez: dedup
    assert len(store.get_fills(sid)) == 1
    assert store.get_fills(sid)[0]["closed_pnl"] == 0.02
    assert len(store.get_funding(sid)) == 1
