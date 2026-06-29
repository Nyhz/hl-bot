from fastapi.testclient import TestClient
from hlbot.api import create_app
from hlbot.models import MarketState, Candle
from hlbot.session_engine import SessionEngine
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
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    assert r.status_code == 200
    assert engine.state.value == "scanning"

def test_kill_requires_confirm_flag():
    client, engine = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    r = client.post("/session/kill", json={"confirm": False},
                    headers={"X-Control-Token": TOKEN})
    assert r.status_code == 400
