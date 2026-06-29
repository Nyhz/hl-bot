import pytest
from hlbot.models import (
    MarketState, Candle, RiskLimits, SessionConfig, SessionState, ActionType,
)
from hlbot.session_engine import SessionEngine

class FakeClient:
    def __init__(self):
        self.orders = []
        self.closed = []
        self._mid = {"ETH": 3000.0}
    def mid(self, coin): return self._mid[coin]
    def user_state(self): return {"assetPositions": [], "marginSummary": {"accountValue": "40"}}
    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        self.orders.append((coin, is_buy, price, size, reduce_only, post_only)); return {"status": "ok"}
    def market_close(self, coin): self.closed.append(coin); return {"status": "ok"}
    def cancel_all(self, coin): pass

class FakeStore:
    def __init__(self): self.decisions = []; self.sid = 1
    def create_session(self, watchlist, capital): return self.sid
    def end_session(self, sid): pass
    def record_decision(self, sid, coin, action, reason): self.decisions.append((coin, action, reason))
    def record_risk_event(self, sid, kind, detail): pass
    def record_pnl_snapshot(self, sid, pnl): pass

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def _flat_ms():
    candles = [Candle(t=i, open=3000, high=3001, low=2999, close=3000, volume=1.0)
               for i in range(1, 60)]
    return {"ETH": MarketState(coin="ETH", mid=3000.0, candles=candles)}

def test_launch_moves_to_scanning():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    assert eng.state == SessionState.SCANNING

def test_launch_rejected_when_not_idle():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    with pytest.raises(RuntimeError):
        eng.launch(_cfg())

def test_tick_places_grid_orders_when_flat():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    assert len(client.orders) > 0

def test_close_blocks_new_orders():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.close()
    assert eng.state == SessionState.CLOSING
    eng.tick(_flat_ms())
    # en CLOSING no se abren nuevas (no reduce_only)
    assert all(o[4] is True for o in client.orders) or client.orders == []

def test_kill_requires_confirmation_and_closes_all():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    with pytest.raises(ValueError):
        eng.kill(confirm=False)
    eng.kill(confirm=True)
    assert eng.state == SessionState.IDLE
    assert "ETH" in client.closed

def test_snapshot_exposes_triggers_and_conditions():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    snap = eng.snapshot(_flat_ms())
    assert snap["state"] == "scanning"
    assert "ETH" in snap["coins"]
    assert "triggers" in snap["coins"]["ETH"]
    assert "conditions" in snap["coins"]["ETH"]

def test_grid_orders_are_maker_post_only():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    assert client.orders
    assert all(o[5] is True for o in client.orders)  # post_only -> maker (TIF Alo)


def test_closing_reduce_only_bypasses_risk_and_keeps_closing():
    from hlbot.models import Decision, ActionType, Side, RiskLimits, SessionConfig

    class FakeClientWithPosition(FakeClient):
        def user_state(self):
            return {"assetPositions": [{"position": {"coin": "ETH"}}],
                    "marginSummary": {"accountValue": "40"}}

    # límite de 1 posición: una apertura normal sería rechazada; reduce_only debe pasar igual
    limits = RiskLimits(15.0, 1, 2.0, 5.0, 20.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)

    client = FakeClientWithPosition()
    eng = SessionEngine(client, FakeStore())
    eng.launch(cfg)

    class _Stub:
        def is_trending(self, ms):
            return False
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_LIMIT, side=Side.BUY,
                             price=2950.0, size=0.01, reduce_only=True, reason="reduce")]
        def armed_triggers(self, ms):
            return []
        def conditions(self, ms):
            return []

    eng.grids["ETH"] = _Stub()
    eng.trends["ETH"] = _Stub()

    eng.close()                 # -> CLOSING
    eng.tick(_flat_ms())
    assert eng.state == SessionState.CLOSING          # reduce_only NO reactiva a ACTIVE
    assert any(o[4] is True for o in client.orders)   # la orden reduce_only se colocó (risk no la bloqueó)
