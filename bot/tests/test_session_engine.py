import pytest
from hlbot.models import (
    MarketState, Candle, RiskLimits, SessionConfig, SessionState, ActionType,
)
from hlbot.session_engine import SessionEngine

class FakeClient:
    def __init__(self):
        self.orders = []
        self.closed = []
        self.stops = []
        self.canceled = []
        self.resting = []
        self._mid = {"ETH": 3000.0}
        self.account_value = "40"
        self.positions = []
    def mid(self, coin): return self._mid[coin]
    def user_state(self):
        return {"assetPositions": self.positions,
                "marginSummary": {"accountValue": self.account_value}}
    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        self.orders.append((coin, is_buy, price, size, reduce_only, post_only)); return {"status": "ok"}
    def place_stop(self, coin, is_buy, trigger_px, size, reduce_only=True):
        self.stops.append((coin, is_buy, trigger_px, size, reduce_only)); return {"status": "ok"}
    def market_close(self, coin): self.closed.append(coin); return {"status": "ok"}
    def cancel_all(self, coin): self.canceled.append(coin)
    def open_orders(self, coin): return list(self.resting)

class FakeStore:
    def __init__(self): self.decisions = []; self.sid = 1
    def create_session(self, watchlist, capital, mode="testnet"): return self.sid
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


def test_loss_limit_triggers_auto_close():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())                                   # session_start_value = 40
    client.account_value = "34"                          # total_pnl = -6 <= -5 (daily limit)
    client.positions = [{"position": {"coin": "ETH"}}]   # 1 posición abierta -> no auto-reset
    eng.tick(_flat_ms())
    assert eng.paused is True
    assert eng.state == SessionState.CLOSING

def test_daily_anchor_resets_on_new_local_day():
    from datetime import date
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng._today_local = lambda: date(2099, 1, 2)          # fuerza cambio de día
    client.account_value = "100"
    eng.tick(_flat_ms())
    assert eng.day_anchor_value == 100.0                 # re-anclado al nuevo día

def test_launch_rejects_unaffordable_grid():
    eng = SessionEngine(FakeClient(), FakeStore())
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=20.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)   # 4*10=40 > 20
    with pytest.raises(ValueError):
        eng.launch(cfg)

def test_grid_skips_rungs_with_resting_order():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())                       # 1er tick coloca rungs
    placed = [o[2] for o in client.orders]     # precios colocados
    assert placed
    client.resting = [{"limitPx": p} for p in placed]   # ahora en reposo (forma de open_orders)
    client.orders.clear()
    eng.tick(_flat_ms())                       # 2º tick: no debe duplicar
    assert client.orders == []


def test_close_cancels_resting_orders():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.close()
    assert "ETH" in client.canceled        # canceló reposo de la watchlist
    assert client.closed == []             # NO liquidó posiciones a mercado


def test_trend_stop_placed_once_and_no_reentry():
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH"}}]   # hay posición abierta tras abrir
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [
                Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY, size=0.004, reason="t"),
                Decision("ETH", ActionType.SET_STOP, side=Side.SELL, price=2940.0,
                         size=0.004, reduce_only=True, reason="stop"),
            ]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())
    assert len(client.stops) == 1                 # stop colocado
    market_opens = [o for o in client.orders if o[5] is False]  # post_only False = market
    assert len(market_opens) == 1                 # abrió una vez
    eng.tick(_flat_ms())
    assert len(client.stops) == 1                 # no recoloca stop
    market_opens = [o for o in client.orders if o[5] is False]
    assert len(market_opens) == 1                 # no reabre tendencia


def test_trend_no_double_entry_before_fill_visible():
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY,
                             size=0.004, reason="t")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())                 # abre (posición aún no visible en user_state)
    eng.tick(_flat_ms())                 # latencia de fill: sigue sin verse
    opens = [o for o in client.orders if o[5] is False]
    assert len(opens) == 1               # NO reabre pese a no estar confirmada

def test_snapshot_has_armed_and_mode():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    snap = eng.snapshot(_flat_ms())
    assert snap["mode"] in ("testnet", "mainnet")
    assert "armed" in snap["coins"]["ETH"]
    assert "session_id" in snap and snap["session_started_at"] is not None


def test_trend_reentry_after_external_close():
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY,
                             size=0.004, reason="t")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())                                  # abre
    client.positions = [{"position": {"coin": "ETH"}}]    # fill visible -> confirmada
    eng.tick(_flat_ms())                                  # no reabre
    client.positions = []                                 # stop ejecutado -> cerrada
    eng.tick(_flat_ms())                                  # permite reentrada
    opens = [o for o in client.orders if o[5] is False]
    assert len(opens) == 2
