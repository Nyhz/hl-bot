"""Recuperación al arranque: rehidratar la última sesión viva o modo seguro."""
from hlbot.config import Config
from hlbot.main import recover_session
from hlbot.models import SessionState
from hlbot.session_engine import SessionEngine
from hlbot.store import Store

from test_session_engine import FakeClient, _cfg


def _setup(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    cfg = Config(testnet=True)
    return store, cfg


def _launch_and_crash(store):
    # Sesión real en la BD con runtime persistido; "crash" = nuevo engine limpio.
    client = FakeClient()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    return eng.session_id


def test_recover_rehydrates_latest_open_session(tmp_path):
    store, cfg = _setup(tmp_path)
    sid = _launch_and_crash(store)
    msgs = []
    eng = SessionEngine(FakeClient(), store)
    recover_session(eng, eng.client, store, cfg, notifier=msgs.append)
    assert eng.session_id == sid
    assert eng.state == SessionState.SCANNING
    assert eng.cfg.watchlist == ["ETH"] and eng.risk is not None
    assert any("rehidratada" in m for m in msgs)
    assert any(e["kind"] == "rehydrate" for e in _events(store, sid))


def _events(store, sid):
    with store._conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM risk_events WHERE session_id=?", (sid,)).fetchall()]


def test_recover_archives_older_orphans(tmp_path):
    store, cfg = _setup(tmp_path)
    old_sid = _launch_and_crash(store)
    new_sid = _launch_and_crash(store)
    eng = SessionEngine(FakeClient(), store)
    recover_session(eng, eng.client, store, cfg, notifier=lambda m: None)
    assert eng.session_id == new_sid                       # rehidrata la más reciente
    assert store.get_session(old_sid)["ended_at"] is not None   # la vieja, archivada
    assert store.get_session(new_sid)["ended_at"] is None


def test_recover_without_payload_archives_and_cleans(tmp_path):
    # sesión de una versión anterior (sin session_runtime): no rehidratable ->
    # archivar y cancelar el reposo huérfano del exchange
    store, cfg = _setup(tmp_path)
    sid = store.create_session(["ETH"], 40.0, mode="testnet")   # sin runtime
    client = FakeClient()
    client.resting.append({"coin": "ETH", "limitPx": 2990.0, "sz": 0.004, "oid": 42})
    msgs = []
    eng = SessionEngine(client, store)
    recover_session(eng, client, store, cfg, notifier=msgs.append)
    assert eng.state == SessionState.IDLE                  # no operó a ciegas
    assert store.get_session(sid)["ended_at"] is not None
    assert ("ETH", 42) in client.canceled_oids             # reposo huérfano cancelado
    assert any("huerfana" in m for m in msgs)


def test_recover_corrupt_payload_archives_and_cleans(tmp_path):
    store, cfg = _setup(tmp_path)
    sid = _launch_and_crash(store)
    store.save_runtime(sid, "{esto no es json")
    msgs = []
    eng = SessionEngine(FakeClient(), store)
    recover_session(eng, eng.client, store, cfg, notifier=msgs.append)
    assert eng.state == SessionState.IDLE and eng.session_id is None
    assert store.get_session(sid)["ended_at"] is not None
    assert any("FALLIDA" in m for m in msgs)


def test_recover_no_sessions_notifies_orphan_positions(tmp_path):
    # sin nada que reanudar pero con posición en el exchange: avisar (usa Kill),
    # sin liquidar por su cuenta
    store, cfg = _setup(tmp_path)
    client = FakeClient()
    client.positions = [{"position": {"coin": "BTC", "szi": "-0.001", "positionValue": "50"}}]
    msgs = []
    eng = SessionEngine(client, store)
    recover_session(eng, client, store, cfg, notifier=msgs.append)
    assert eng.state == SessionState.IDLE
    assert client.closed == []                             # NO liquidó
    assert msgs and "BTC" in msgs[0] and "Kill" in msgs[0]


def test_recover_clean_start_is_silent(tmp_path):
    store, cfg = _setup(tmp_path)
    msgs = []
    eng = SessionEngine(FakeClient(), store)
    recover_session(eng, eng.client, store, cfg, notifier=msgs.append)
    assert eng.state == SessionState.IDLE
    assert msgs == []                                      # arranque limpio: ni ruido
