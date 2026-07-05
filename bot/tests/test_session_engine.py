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
        self.canceled_oids = []
        self.resting = []
        self._mid = {"ETH": 3000.0}
        self.account_value = "40"
        self.positions = []
        self.leverage_set = []
        self.market_opens = []
        self._next_oid = 1000
    def mid(self, coin): return self._mid[coin]
    def set_leverage(self, coin, leverage, is_cross=False):
        self.leverage_set.append((coin, leverage, is_cross)); return {"status": "ok"}
    def market_open(self, coin, is_buy, size, slippage=0.01):
        self.market_opens.append((coin, is_buy, size)); return {"status": "ok"}
    def user_state(self):
        return {"assetPositions": self.positions,
                "marginSummary": {"accountValue": self.account_value}}
    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        self._next_oid += 1
        self.orders.append((coin, is_buy, price, size, reduce_only, post_only))
        self.resting.append({"coin": coin, "limitPx": price, "sz": size, "oid": self._next_oid})
        return {"status": "ok"}
    def cancel_order(self, coin, oid):
        self.canceled_oids.append((coin, oid))
    def place_stop(self, coin, is_buy, trigger_px, size, reduce_only=True):
        self._next_oid += 1
        self.stops.append((coin, is_buy, trigger_px, size, reduce_only))
        return {"resp": {"status": "ok"}, "oid": self._next_oid}
    def market_close(self, coin): self.closed.append(coin); return {"status": "ok"}
    def cancel_all(self, coin): self.canceled.append(coin)
    def open_orders(self, coin): return list(self.resting)

class FakeStore:
    def __init__(self):
        self.decisions = []; self.sid = 1; self.ended = []; self.risk_events = []
    def create_session(self, watchlist, capital, mode="testnet"): return self.sid
    def end_session(self, sid): self.ended.append(sid)
    def record_decision(self, sid, coin, action, reason): self.decisions.append((coin, action, reason))
    def record_risk_event(self, sid, kind, detail): self.risk_events.append((kind, detail))
    def record_pnl_snapshot(self, sid, pnl): pass

def _cfg():
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0)
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
    limits = RiskLimits(10.0, 1, 2.0, 5.0, 20.0)
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
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=20.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)   # 4*$10=40 > 20
    with pytest.raises(ValueError):
        eng.launch(cfg)

def test_launch_rejects_position_below_min():
    eng = SessionEngine(FakeClient(), FakeStore())
    limits = RiskLimits(5.0, 4, 2.0, 5.0, 20.0)          # posición $5 < mínimo $10
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)
    with pytest.raises(ValueError):
        eng.launch(cfg)

def test_grid_reconcile_cancels_stale_and_places_missing():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())                       # coloca la escalera inicial
    n_first = len(client.orders)
    assert n_first > 0
    # mover el mid -> la referencia se mueve -> rungs viejos quedan stale
    moved = _flat_ms()
    moved["ETH"].mid = 3000.0 * 1.01           # mid se mueve -> la referencia se mueve
    eng.tick(moved)
    assert client.canceled_oids                # canceló al menos un rung stale

def test_grid_reconcile_no_churn_when_unchanged():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    client.orders.clear(); client.canceled_oids.clear()
    eng.tick(_flat_ms())                       # mismo estado -> sin cambios
    assert client.orders == []
    assert client.canceled_oids == []


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
                Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY, size=0.003, reason="t"),
                Decision("ETH", ActionType.SET_STOP, side=Side.SELL, price=2940.0,
                         size=0.003, reduce_only=True, reason="stop"),
            ]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())
    assert len(client.stops) == 1                 # stop colocado
    assert len(client.market_opens) == 1          # abrió una vez (market real)
    eng.tick(_flat_ms())
    assert len(client.stops) == 1                 # no recoloca stop
    assert len(client.market_opens) == 1          # no reabre tendencia


def test_trend_no_double_entry_before_fill_visible():
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY,
                             size=0.003, reason="t")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())                 # abre (posición aún no visible en user_state)
    eng.tick(_flat_ms())                 # latencia de fill: sigue sin verse
    assert len(client.market_opens) == 1 # NO reabre pese a no estar confirmada

def test_snapshot_has_armed_and_mode():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    snap = eng.snapshot(_flat_ms())
    assert snap["mode"] in ("testnet", "mainnet")
    assert "armed" in snap["coins"]["ETH"]
    assert "session_id" in snap and snap["session_started_at"] is not None

def test_snapshot_exposes_funding_rate():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    ms = _flat_ms()
    ms["ETH"].funding_rate = 0.0000125
    snap = eng.snapshot(ms)
    assert snap["coins"]["ETH"]["funding"] == 0.0000125


def test_launch_sets_isolated_leverage_per_coin():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    assert ("ETH", 2, False) in client.leverage_set   # max_leverage=2, isolated

def test_leverage_guard_blocks_when_real_leverage_exceeds():
    client = FakeClient()
    # posición BTC de $75 de notional + equity 40 -> añadir $10 da lev 2.125 > 2
    client.positions = [{"position": {"coin": "BTC", "positionValue": "75"}}]
    client.account_value = "40"
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    assert client.orders == []                         # todos los rungs rechazados por leverage

def test_per_coin_cap_blocks_growth():
    client = FakeClient()
    # posición ETH de $25; equity alto (leverage no bloquea); cap por moneda $30
    client.positions = [{"position": {"coin": "ETH", "positionValue": "25"}}]
    client.account_value = "1000"
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)
    eng = SessionEngine(client, FakeStore())
    eng.launch(cfg)
    eng.tick(_flat_ms())
    assert client.orders == []                         # 25 + 10 > 30 -> bloqueado por moneda

def test_grid_canceled_once_on_trend_regime_switch():
    from hlbot.models import MarketState
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms): return []
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())
    eng.tick(_flat_ms())
    assert client.canceled == ["ETH"]                  # cancelado una sola vez al entrar en tendencia

def test_trend_reentry_after_external_close():
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY,
                             size=0.003, reason="t")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())                                  # abre
    client.positions = [{"position": {"coin": "ETH"}}]    # fill visible -> confirmada
    eng.tick(_flat_ms())                                  # no reabre
    client.positions = []                                 # stop ejecutado -> cerrada
    eng.tick(_flat_ms())                                  # permite reentrada
    assert len(client.market_opens) == 2

def test_tick_populates_inventory_from_user_state():
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.0064", "positionValue": "10.1"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    ms = _flat_ms()
    eng.tick(ms)
    assert abs(ms["ETH"].inventory - 0.0064) < 1e-9


def test_engine_trailing_stop_only_improves(monkeypatch):
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.004", "positionValue": "12"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.trend_open.add("ETH")

    levels = iter([2940.0, 2950.0, 2945.0])  # mejora, mejora, empeora
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.SET_STOP, side=Side.SELL,
                             price=next(levels), size=0.004, reduce_only=True, reason="trail")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())   # coloca stop 2940
    eng.tick(_flat_ms())   # 2950 mejora -> cancela+recoloca
    eng.tick(_flat_ms())   # 2945 empeora -> no toca
    assert len(client.stops) == 2          # solo dos colocaciones (inicial + 1 mejora)
    assert len(client.canceled_oids) == 1  # canceló el trigger viejo una vez


def test_regime_does_not_cancel_while_trend_position_held():
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.004", "positionValue": "12"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.trend_open.add("ETH")
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms): return []
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()
    before = len(client.canceled)
    eng.tick(_flat_ms())
    assert len(client.canceled) == before   # no se cancela el grid/stop mientras hay posición de tendencia


def test_engine_trailing_stop_short_only_improves(monkeypatch):
    """BUY stop trailing para posición corta: mejora bajando, no sube."""
    from hlbot.models import Decision, ActionType, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "-0.004", "positionValue": "12"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.trend_open.add("ETH")

    # Con velas planas ATR≈1, thr≈0.1; un salto de 10 mejora (baja), uno de 5 empeora (sube).
    levels = iter([2060.0, 2050.0, 2055.0])  # inicial, mejora DOWN, empeora UP -> no toca
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.SET_STOP, side=Side.BUY,
                             price=next(levels), size=0.004, reduce_only=True, reason="trail")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())   # coloca BUY stop a 2060
    eng.tick(_flat_ms())   # 2050 < 2060 - 0.1 -> mejora -> cancela + recoloca
    eng.tick(_flat_ms())   # 2055 > 2050 -> empeora -> no toca
    assert len(client.stops) == 2          # solo dos colocaciones (inicial + 1 mejora)
    assert len(client.canceled_oids) == 1  # canceló el stop viejo una vez


def test_decisions_grid_position_not_hijacked_by_trend():
    # posición de GRID abierta (inventory>0, NO en trend_open) y régimen de tendencia:
    # debe seguir gestionándola el GRID, no momentum.
    from hlbot.models import MarketState, ActionType, Decision
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.CLOSE, reduce_only=True, reason="no debería")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()
    ms = MarketState(coin="ETH", mid=3000.0, candles=[], inventory=0.01)  # posición de grid
    ds = eng._decisions_for(ms)
    assert all(d.action != ActionType.CLOSE for d in ds)   # NO lo cierra momentum
    # son decisiones del grid (place_limit) o vacío, nunca el CLOSE del stub de tendencia


def test_decisions_trend_position_managed_by_trend():
    from hlbot.models import MarketState, ActionType, Decision
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    eng.trend_open.add("ETH")
    class _Trend:
        def is_trending(self, ms): return False
        def evaluate(self, ms): return [Decision("ETH", ActionType.SET_STOP, reason="trail")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()
    ms = MarketState(coin="ETH", mid=3000.0, candles=[], inventory=0.01)
    ds = eng._decisions_for(ms)
    assert any(d.action == ActionType.SET_STOP for d in ds)  # lo gestiona momentum


def test_decisions_flat_trending_enters_trend():
    from hlbot.models import MarketState, ActionType, Decision
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms): return [Decision("ETH", ActionType.PLACE_MARKET, reason="entra")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()
    ms = MarketState(coin="ETH", mid=3000.0, candles=[], inventory=0.0)  # plano
    ds = eng._decisions_for(ms)
    assert any(d.action == ActionType.PLACE_MARKET for d in ds)  # momentum entra


def test_close_raises_without_active_session():
    # tras un reinicio del proceso (estado IDLE) el botón de cerrar debe dar error
    # explícito, no un 200 silencioso que no hace nada
    eng = SessionEngine(FakeClient(), FakeStore())
    with pytest.raises(RuntimeError):
        eng.close()


def test_closing_actively_closes_positions_each_tick():
    # el grid no tiene salida propia: en CLOSING el engine debe liquidar a mercado
    # y reintentar cada tick hasta quedar plano (bug de la sesión de 90h)
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.close()
    eng.tick(_flat_ms())
    assert client.closed == ["ETH"]                   # liquidó a mercado
    assert eng.state == SessionState.CLOSING          # posición aún visible -> sigue cerrando
    eng.tick(_flat_ms())
    assert client.closed == ["ETH", "ETH"]            # reintenta en el siguiente tick


def test_closing_ends_session_in_store_when_flat():
    store = FakeStore()
    eng = SessionEngine(FakeClient(), store)
    eng.launch(_cfg())
    eng.close()
    eng.tick(_flat_ms())                              # sin posiciones -> termina
    assert eng.state == SessionState.IDLE
    assert store.ended == [1]                         # ended_at grabado en BD


def test_closing_records_error_when_market_close_rejected():
    # el SDK devuelve rechazos como statuses con 'error' SIN excepción: hay que
    # detectarlos y dejar rastro, no darlos por buenos
    class _RejClient(FakeClient):
        def market_close(self, coin):
            super().market_close(coin)
            return {"status": "ok", "response": {"data": {"statuses": [
                {"error": "Order could not immediately match"}]}}}
    client = _RejClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    eng.close()
    eng.tick(_flat_ms())
    assert any(k == "close_error" for k, _ in store.risk_events)
    assert eng.state == SessionState.CLOSING


def test_kill_raises_when_positions_remain():
    # kill no debe fingir éxito: si tras cerrar sigue habiendo posiciones,
    # error explícito y la sesión queda viva para reintentar
    client = FakeClient()                              # market_close no vacía positions
    client.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    with pytest.raises(RuntimeError):
        eng.kill(confirm=True)
    assert eng.session_id == 1                         # sesión NO finiquitada en falso
    assert store.ended == []
    assert any(k == "kill_error" for k, _ in store.risk_events)


def test_kill_success_when_positions_clear():
    class _OkClient(FakeClient):
        def market_close(self, coin):
            r = super().market_close(coin)
            self.positions = [p for p in self.positions
                              if p["position"]["coin"] != coin]
            return r
    client = _OkClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    eng.kill(confirm=True)
    assert eng.state == SessionState.IDLE
    assert store.ended == [1]


def test_kill_closes_orphan_positions_without_session():
    # tras un reinicio: cfg=None pero hay posiciones reales en el exchange;
    # kill debe operar sobre user_state, no sobre la watchlist perdida
    class _OkClient(FakeClient):
        def market_close(self, coin):
            r = super().market_close(coin)
            self.positions = [p for p in self.positions
                              if p["position"]["coin"] != coin]
            return r
    client = _OkClient()
    client.positions = [{"position": {"coin": "BTC", "szi": "-0.001", "positionValue": "50"}}]
    eng = SessionEngine(client, FakeStore())           # sin launch
    eng.kill(confirm=True)
    assert "BTC" in client.closed
    assert "BTC" in client.canceled
    assert eng.state == SessionState.IDLE


def test_grid_exit_rung_allowed_at_coin_cap():
    # largo en el cap por moneda: el rung SELL que REDUCE inventario no debe ser
    # rechazado por max_coin_notional (origen de la posición congelada + 37k rechazos)
    from hlbot.models import Decision, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    client.account_value = "1000"
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)     # cap por moneda ya alcanzado
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(cfg)

    class _Grid:
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_LIMIT, side=Side.SELL,
                             price=3010.0, size=0.005, reason="rung de salida")]
        def half_spread(self, ms, sigma): return 1.0
        def _sigma(self, ms): return 1.0
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []

    class _NoTrend:
        def is_trending(self, ms): return False
        def evaluate(self, ms): return []
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []

    eng.grids["ETH"] = _Grid()
    eng.trends["ETH"] = _NoTrend()
    eng.tick(_flat_ms())
    sells = [o for o in client.orders if o[1] is False]    # is_buy=False
    assert sells                                           # el rung reductor se colocó


def test_engine_has_lock_and_is_free():
    import threading
    eng = SessionEngine(FakeClient(), FakeStore())
    assert isinstance(eng.lock, type(threading.Lock()))
    assert eng.lock.acquire(blocking=False) is True   # libre
    eng.lock.release()
