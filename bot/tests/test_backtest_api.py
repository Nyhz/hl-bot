from fastapi.testclient import TestClient
from hlbot.api import create_app
from hlbot.session_engine import SessionEngine
from test_session_engine import FakeClient, FakeStore

TOKEN = "t"

class BTClient(FakeClient):
    sz_decimals = {"ETH": 4}
    def candles(self, coin, interval, start, end):
        return [{"t": i * 60000, "o": 3000, "h": 3005, "l": 2995, "c": 3000, "v": 1}
                for i in range(1, 80)]
    class _Info:
        @staticmethod
        def funding_history(coin, start_ms): return []
    info = _Info()

def _client():
    eng = SessionEngine(BTClient(), FakeStore())
    return TestClient(create_app(eng, TOKEN, lambda: {}))

def test_backtest_returns_result_no_token_needed():
    c = _client()
    r = c.post("/backtest", json={"coin": "ETH", "capital": 1000.0, "n_candles": 79})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"metrics", "equity_curve", "trades", "decisions"}
    assert "net_pnl" in body["metrics"]

def test_backtest_bad_coin_returns_422():
    c = _client()
    r = c.post("/backtest", json={"coin": "NOPE", "capital": 1000.0, "n_candles": 50})
    assert r.status_code == 422

def test_backtest_empty_candles_returns_422():
    class EmptyClient(BTClient):
        def candles(self, coin, interval, start, end): return []
    eng = SessionEngine(EmptyClient(), FakeStore())
    c = TestClient(create_app(eng, TOKEN, lambda: {}))
    r = c.post("/backtest", json={"coin": "ETH", "capital": 1000.0, "n_candles": 50})
    assert r.status_code == 422

def test_backtest_invalid_params_returns_422():
    c = _client()
    r = c.post("/backtest", json={"coin": "ETH", "capital": 1000.0, "n_candles": 50,
                                  "max_position_notional": 5.0})
    assert r.status_code == 422
