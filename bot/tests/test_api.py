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
