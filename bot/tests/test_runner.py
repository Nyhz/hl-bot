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
    ms, raw, refreshed = build_market_state(_FakeClient(), "ETH", now_ms=999)
    assert ms.coin == "ETH" and ms.mid == 11.5          # fallback REST sin marketdata
    assert len(ms.candles) == 2
    assert raw is RAW and refreshed is True
    assert ms.microprice is None and ms.sigma_px is None  # sin WS: degradado


def test_build_market_state_uses_ws_and_candle_cache():
    from hlbot.marketdata import MarketData

    class _NoMidClient(_FakeClient):
        def mid(self, coin):
            raise AssertionError("con WS fresco no debe pegar al REST de mids")

    md = MarketData("https://x", ["ETH"])                # sin start(): sin red
    md._on_bbo({"data": {"coin": "ETH", "bbo": [
        {"px": "3000", "sz": "10"}, {"px": "3002", "sz": "2"}]}})
    md._on_trades({"data": [
        {"coin": "ETH", "px": "3001", "sz": "1", "side": "B"},
        {"coin": "ETH", "px": "3000", "sz": "0.5", "side": "A"}]})

    cache: dict = {}
    ms, raw, refreshed = build_market_state(_NoMidClient(), "ETH", now_ms=999,
                                            md=md, candle_cache=cache)
    assert ms.mid == 3001.0                              # mid del bbo WS
    assert ms.best_bid == 3000.0 and ms.ask_sz == 2.0
    # microprice cargado hacia el ask (bid 5x más grueso que el ask)
    assert ms.microprice is not None and ms.microprice > ms.mid
    assert ms.flow_usd is not None and ms.flow_usd > 0   # flujo neto comprador
    assert -1.0 <= ms.flow_ratio <= 1.0
    assert refreshed is True and "ETH" in cache
    # segunda llamada dentro del TTL: velas de caché, sin REST
    class _NoCandles(_NoMidClient):
        def candles(self, *a):
            raise AssertionError("velas dentro del TTL deben salir de la caché")
    ms2, raw2, refreshed2 = build_market_state(_NoCandles(), "ETH", now_ms=1000,
                                               md=md, candle_cache=cache)
    assert refreshed2 is False and raw2 is RAW


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


def test_dms_armed_and_rearmed_with_session():
    # con sesión activa el runner arma el dead man's switch del exchange y lo
    # re-arma por cadencia: si el proceso muere, HL cancela solo todo el reposo
    import time
    from hlbot.main import run_tick, DMS_EVERY_TICKS
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_run_cfg())
    counters = {"loop": 0, "ticks": 0}
    run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)
    assert len(eng.client.scheduled_cancels) == 1
    assert eng.client.scheduled_cancels[0] > int(time.time() * 1000)  # cancel-all diferido
    for _ in range(DMS_EVERY_TICKS):
        run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)
    assert len(eng.client.scheduled_cancels) == 2   # re-armado una vez por cadencia


def test_dms_disarmed_when_session_ends():
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_run_cfg())
    counters = {"loop": 0, "ticks": 0}
    run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)      # arma
    eng._reset()                                                       # sesión terminada
    run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)      # desarma
    assert eng.client.scheduled_cancels[-1] is None
    run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)      # ya desarmado: no repite
    assert eng.client.scheduled_cancels.count(None) == 1


def test_dms_expired_clears_stop_tracking():
    # tick congelado > horizonte: el exchange ya disparó el cancel-all (stops de
    # tendencia incluidos); el runner debe olvidarlos para que el engine los
    # recoloque, no creer que siguen puestos con la posición desnuda
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_run_cfg())
    eng.stop_levels["ETH"] = 2900.0
    eng.stop_oids["ETH"] = 111
    counters = {"loop": 0, "ticks": 0, "dms_armed": True, "dms_last_arm_ms": 1}
    run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)
    assert eng.stop_levels == {} and eng.stop_oids == {}
    assert eng.client.scheduled_cancels                    # y re-armó inmediatamente


def test_dms_volume_gated_disables_after_first_rejection():
    # HL gatea scheduleCancel a $1M de volumen acumulado y responde status=err SIN
    # excepción: hay que desactivarlo (protege el watchdog), no reintentarlo cada tick
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine

    class _Gated(FakeClient):
        def schedule_cancel(self, at_ms):
            super().schedule_cancel(at_ms)
            return {"status": "err",
                    "response": "Cannot set scheduled cancel time until enough volume traded."}

    eng = SessionEngine(_Gated(), FakeStore())
    eng.launch(_run_cfg())
    counters = {"loop": 0, "ticks": 0}
    for _ in range(3):
        run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters)
    assert len(eng.client.scheduled_cancels) == 1      # un intento y desactivado
    assert not counters.get("dms_armed")
    assert counters.get("dms_unavailable") is True


def test_run_tick_writes_heartbeat(tmp_path, monkeypatch):
    import hlbot.main as m
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    monkeypatch.setattr(m, "HEARTBEAT_FILE", str(tmp_path / "hb"))
    eng = SessionEngine(FakeClient(), FakeStore())
    m.run_tick(eng, eng.client, eng.store, {}, {"v": {}}, {"loop": 0, "ticks": 0})
    assert float((tmp_path / "hb").read_text()) > 0    # latido para el watchdog


def test_update_markouts_computes_signed_bps(tmp_path):
    import time
    from hlbot.main import update_markouts
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["BTC"], 40.0, mode="testnet")
    now = time.time()
    # compra a 100 hace 40s y venta a 100 hace 40s
    store.record_fill_unique(sid, "t1", int(now - 40), "BTC", "B", "Open Long", 100.0, 0.1, 0.0, 0.0)
    store.record_fill_unique(sid, "t2", int(now - 40), "BTC", "A", "Open Short", 100.0, 0.1, 0.0, 0.0)

    class _Md:
        def mid_at(self, coin, ts, tol_s=2.0):
            return 101.0                        # el precio subió tras el fill

    update_markouts(store, _Md(), sid)
    fills = store.get_fills(sid)
    by_side = {f["side"]: f for f in fills}
    assert abs(by_side["B"]["markout_5s"] - 100.0) < 1e-6    # +100 bps a favor
    assert abs(by_side["A"]["markout_5s"] + 100.0) < 1e-6    # -100 bps (vendió y subió)
    assert by_side["B"]["markout_30s"] is not None           # 30s también vencido
    # segunda pasada: ya no hay pendientes (no recalcula)
    class _Boom:
        def mid_at(self, coin, ts, tol_s=2.0):
            raise AssertionError("no debe consultar fills ya resueltos")
    update_markouts(store, _Boom(), sid)


def test_update_markouts_skips_when_no_history(tmp_path):
    import time
    from hlbot.main import update_markouts
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["BTC"], 40.0, mode="testnet")
    store.record_fill_unique(sid, "t1", int(time.time() - 40), "BTC", "B", "", 100.0, 0.1, 0.0, 0.0)

    class _Md:
        def mid_at(self, coin, ts, tol_s=2.0):
            return None                         # hueco del feed

    update_markouts(store, _Md(), sid)
    assert store.get_fills(sid)[0]["markout_5s"] is None     # queda pendiente, sin inventar


def test_funding_cached_between_ticks():
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    from hlbot.models import RiskLimits, SessionConfig
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(SessionConfig(watchlist=["ETH"], capital=40.0,
                             limits=RiskLimits(10.0, 4, 2.0, 5.0, 20.0),
                             grid_n=4, grid_range_pct=0.02))
    counters = {"loop": 0, "ticks": 0}
    fcache: dict = {}
    for _ in range(3):
        run_tick(eng, eng.client, eng.store, {}, {"v": {}}, counters,
                 None, {}, fcache)
    assert eng.client.funding_calls == 1        # 3 ticks, 1 sola llamada REST


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
