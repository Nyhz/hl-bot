from fastapi.testclient import TestClient
from hlbot.api import create_app
from hlbot.models import MarketState, Candle
from hlbot.session_engine import SessionEngine
from hlbot.store import Store
from test_session_engine import FakeClient, FakeStore  # pytest expone el modulo por nombre simple

TOKEN = "secret-tok"

def _provider():
    candles = [Candle(t=i, open=3000, high=3001, low=2999, close=3000, volume=1.0)
               for i in range(1, 60)]
    return {"ETH": MarketState(coin="ETH", mid=3000.0, candles=candles)}

def _client():
    engine = SessionEngine(FakeClient(), FakeStore())
    app = create_app(engine, TOKEN, _provider)
    return TestClient(app), engine

def test_state_is_idle_initially():
    client, _ = _client()
    r = client.get("/state")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"

def test_launch_requires_token():
    client, _ = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body)
    assert r.status_code == 401

def test_launch_with_token_moves_to_scanning():
    client, engine = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0, "grid_n": 4,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    assert r.status_code == 200
    assert engine.state.value == "scanning"

def test_kill_requires_confirm_flag():
    client, engine = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0, "grid_n": 4,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    r = client.post("/session/kill", json={"confirm": False},
                    headers={"X-Control-Token": TOKEN})
    assert r.status_code == 400

def test_close_from_idle_is_ok():
    client, engine = _client()
    r = client.post("/session/close", headers={"X-Control-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["state"] == "idle"

def test_close_requires_token():
    client, _ = _client()
    r = client.post("/session/close")
    assert r.status_code == 401

def test_launch_unaffordable_grid_returns_422():
    client, _ = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0, "grid_n": 10,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    assert r.status_code == 422


def _client_with_data(tmp_path):
    from hlbot.api import create_app
    from hlbot.session_engine import SessionEngine
    from test_session_engine import FakeClient, FakeStore  # FakeClient tiene sz_decimals? ver nota
    # store real con datos sembrados
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_pnl_snapshot(sid, -0.1); store.record_pnl_snapshot(sid, 0.2)
    store.record_decision(sid, "ETH", "place_limit", "grid rung")
    with store._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO market_candles "
                     "(coin, interval, t, open, high, low, close, volume) "
                     "VALUES ('ETH','1m',60000,10,12,9,11,1)")
    client = FakeClient()
    client.sz_decimals = {"BTC": 5, "ETH": 4, "SOL": 2}
    engine = SessionEngine(client, store)
    engine.session_id = sid
    acct = {"equity": 49.16, "session_pnl": -0.84, "open_count": 1, "max_open": 4,
            "positions": [{"coin": "ETH", "side": "long", "unrealized_pnl": -0.2}],
            "_fills": [{"coin": "ETH", "time": 70000, "dir": "Close Long",
                        "px": "11", "closedPnl": "0.02", "fee": "0.001"}]}
    app = create_app(engine, TOKEN, lambda: {}, lambda: acct)
    return TestClient(app), sid

def test_account_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/account")
    assert r.status_code == 200 and r.json()["equity"] == 49.16

def test_positions_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/positions")
    assert r.status_code == 200 and r.json()[0]["coin"] == "ETH"

def test_equity_curve_endpoint(tmp_path):
    client, sid = _client_with_data(tmp_path)
    r = client.get(f"/equity_curve?session_id={sid}")
    assert [p["total_pnl"] for p in r.json()] == [-0.1, 0.2]

def test_candles_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/candles/ETH")
    assert r.json()[0] == {"time": 60, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}

def test_tape_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/tape")
    kinds = {e["kind"] for e in r.json()}
    assert "close" in kinds and "decision" in kinds

def test_coins_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/coins")
    names = [c["name"] for c in r.json()]
    assert "BTC" in names and "ETH" in names and "SOL" in names

def test_state_includes_account_and_tape(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/state")
    body = r.json()
    assert "account" in body and "positions" in body and "tape_recent" in body


def _seed_two_sessions(tmp_path):
    from hlbot.store import Store
    store = Store(str(tmp_path / "tr.db")); store.init_schema()
    s1 = store.create_session(["ETH"], 40.0, mode="testnet")
    store.record_fill_unique(s1, "t1", 100, "ETH", "B", "Close Long", 3000, 0.004, 0.0015, 0.05)
    store.record_pnl_snapshot(s1, 0.03)
    s2 = store.create_session(["BTC"], 50.0, mode="mainnet")
    store.record_fill_unique(s2, "t2", 200, "BTC", "A", "Close Short", 67000, 0.0002, 0.001, -0.04)
    store.record_pnl_snapshot(s2, -0.05)
    return store, s1, s2

def _api_with_store(store):
    from hlbot.api import create_app
    from hlbot.session_engine import SessionEngine
    from test_session_engine import FakeClient
    engine = SessionEngine(FakeClient(), store)
    return TestClient(create_app(engine, TOKEN, lambda: {}, lambda: {}))

def test_session_detail_404(tmp_path):
    store, _, _ = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    assert client.get("/sessions/99999").status_code == 404

def test_sessions_list_filter_by_mode(tmp_path):
    store, s1, s2 = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    alls = client.get("/sessions").json()
    assert {s["id"] for s in alls} == {s1, s2}
    testnet = client.get("/sessions?mode=testnet").json()
    assert [s["id"] for s in testnet] == [s1]
    assert testnet[0]["realized_pnl"] == 0.05

def test_session_detail(tmp_path):
    store, s1, _ = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    body = client.get(f"/sessions/{s1}").json()
    assert body["summary"]["id"] == s1
    assert len(body["trades"]) == 1 and body["trades"][0]["closed_pnl"] == 0.05
    assert "equity_curve" in body and "decisions" in body

def test_stats_global_separates_modes(tmp_path):
    store, _, _ = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    g = client.get("/stats/global").json()
    assert g["testnet"]["n_sessions"] == 1 and g["mainnet"]["n_sessions"] == 1
    assert abs(g["testnet"]["realized_pnl"] - 0.05) < 1e-9
    assert abs(g["mainnet"]["realized_pnl"] - (-0.04)) < 1e-9
