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
