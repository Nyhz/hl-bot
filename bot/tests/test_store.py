from hlbot.store import Store

def test_create_and_query_session(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH", "BTC"], 40.0)
    assert isinstance(sid, int)

def test_record_and_get_decision(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_decision(sid, "ETH", "place_limit", "grid rung 3000")
    rows = store.get_decisions(sid)
    assert len(rows) == 1
    assert rows[0]["coin"] == "ETH"
    assert rows[0]["reason"] == "grid rung 3000"

def test_record_and_get_fill(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_fill(sid, "ETH", "buy", 3000.0, 0.0034, 0.0015)
    rows = store.get_fills(sid)
    assert len(rows) == 1
    assert rows[0]["price"] == 3000.0

def test_get_pnl_snapshots(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_pnl_snapshot(sid, -0.10)
    store.record_pnl_snapshot(sid, 0.25)
    rows = store.get_pnl_snapshots(sid)
    assert [r["total_pnl"] for r in rows] == [-0.10, 0.25]
    assert "ts" in rows[0]

def test_get_candles(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    with store._conn() as conn:
        for t in (3, 1, 2):  # desordenados a propósito
            conn.execute(
                "INSERT OR REPLACE INTO market_candles "
                "(coin, interval, t, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("ETH", "1m", t, 10.0, 11.0, 9.0, 10.5, 1.0))
    rows = store.get_candles("ETH", "1m", limit=10)
    assert [r["t"] for r in rows] == [1, 2, 3]  # ascendente
    assert rows[0]["close"] == 10.5

def test_init_schema_idempotent_and_adds_columns(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    store.init_schema()  # 2ª vez no debe fallar (migración idempotente)
    with store._conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert "mode" in cols
        fcols = {r[1] for r in conn.execute("PRAGMA table_info(fills)")}
        assert {"tid", "closed_pnl", "dir"} <= fcols

def test_create_session_with_mode_and_list(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    a = store.create_session(["ETH"], 40.0, mode="testnet")
    b = store.create_session(["BTC"], 50.0, mode="mainnet")
    assert store.get_session(a)["mode"] == "testnet"
    testnet_ids = [s["id"] for s in store.list_sessions(mode="testnet")]
    assert a in testnet_ids and b not in testnet_ids
    assert len(store.list_sessions()) == 2  # sin filtro, todas

def test_record_fill_unique_dedups_by_tid(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    for _ in range(2):  # mismo tid dos veces -> una fila
        store.record_fill_unique(sid, "tid1", 100, "ETH", "B", "Close Long",
                                 3000.0, 0.004, 0.0015, 0.02)
    fills = store.get_fills(sid)
    assert len(fills) == 1
    assert fills[0]["closed_pnl"] == 0.02 and fills[0]["dir"] == "Close Long"

def test_record_funding_unique_dedups(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    for _ in range(2):
        store.record_funding_unique(sid, "fk1", 100, "ETH", -0.001)
    f = store.get_funding(sid)
    assert len(f) == 1 and f[0]["amount"] == -0.001
