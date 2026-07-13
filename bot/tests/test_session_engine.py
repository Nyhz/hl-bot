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
        self.scheduled_cancels = []
        self.frontend_orders = []
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
    def schedule_cancel(self, at_ms):
        self.scheduled_cancels.append(at_ms); return {"status": "ok"}
    def all_open_orders(self): return list(self.resting)
    def frontend_open_orders(self): return list(self.frontend_orders)
    def bulk_place_limits(self, coin, items, post_only=True):
        for it in items:
            self._next_oid += 1
            self.orders.append((coin, it["is_buy"], it["price"], it["size"],
                                bool(it.get("reduce_only", False)), post_only))
            self.resting.append({"coin": coin, "limitPx": it["price"],
                                 "sz": it["size"], "oid": self._next_oid})
        return {"status": "ok"}
    def cancel_orders(self, coin, oids):
        self.canceled_oids.extend((coin, o) for o in oids)
        return {"status": "ok"}
    def funding_rates(self):
        self.funding_calls = getattr(self, "funding_calls", 0) + 1
        return {}

class FakeStore:
    def __init__(self):
        self.decisions = []; self.sid = 1; self.ended = []; self.risk_events = []
        self.runtime = None; self.config_json = None
        self.micro = []; self.pnl_snapshots = []
    def create_session(self, watchlist, capital, mode="testnet"): return self.sid
    def end_session(self, sid): self.ended.append(sid)
    def record_decision(self, sid, coin, action, reason): self.decisions.append((coin, action, reason))
    def record_risk_event(self, sid, kind, detail): self.risk_events.append((kind, detail))
    def record_pnl_snapshot(self, sid, pnl, **extras): self.pnl_snapshots.append((pnl, extras))
    def save_runtime(self, sid, payload): self.runtime = payload
    def set_session_config(self, sid, config_json): self.config_json = config_json
    def record_micro_batch(self, sid, rows): self.micro.extend(rows)

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
        def too_toxic(self, ms): return False
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


def test_trend_entry_rejected_not_marked_open():
    # rechazo SIN excepción (p.ej. margen insuficiente): el coin NO debe entrar en
    # trend_open sin posición real (quedaría atascado toda la sesión: bloqueado para
    # el grid y sin reintento de entrada) ni colocarse un stop huérfano
    from hlbot.models import Decision, Side

    class _RejOpen(FakeClient):
        def market_open(self, coin, is_buy, size, slippage=0.01):
            super().market_open(coin, is_buy, size)
            return {"status": "ok", "response": {"data": {"statuses": [
                {"error": "Insufficient margin to place order"}]}}}

    client = _RejOpen()
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())

    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            return [
                Decision("ETH", ActionType.PLACE_MARKET, side=Side.BUY,
                         size=0.003, reason="t"),
                Decision("ETH", ActionType.SET_STOP, side=Side.SELL, price=2940.0,
                         size=0.003, reduce_only=True, reason="stop inicial"),
            ]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())
    assert "ETH" not in eng.trend_open                     # no finge posición
    assert client.stops == []                              # sin posición no hay stop
    assert any(k == "orden_rechazada" for k, _ in store.risk_events)
    eng.tick(_flat_ms())
    assert len(client.market_opens) == 2                   # puede reintentar la entrada


def test_trend_close_rejected_records_event():
    # la salida por reversión también llega como statuses con 'error' sin excepción:
    # hay que dejar rastro (la posición sigue viva y se reintenta al tick siguiente)
    from hlbot.models import Decision

    class _RejClose(FakeClient):
        def market_close(self, coin):
            super().market_close(coin)
            return {"status": "ok", "response": {"data": {"statuses": [
                {"error": "Order could not immediately match"}]}}}

    client = _RejClose()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.003", "positionValue": "10"}}]
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    eng.trend_open.add("ETH")
    eng.trend_confirmed.add("ETH")

    class _Trend:
        def is_trending(self, ms): return False
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.CLOSE, reduce_only=True, reason="reversión")]
        def armed_triggers(self, ms): return []
        def conditions(self, ms): return []
    eng.trends["ETH"] = _Trend()

    eng.tick(_flat_ms())
    assert any(k == "close_error" for k, _ in store.risk_events)
    assert "ETH" in eng.trend_open                         # sigue gestionada por momentum


def test_launch_and_tick_persist_runtime():
    import json
    store = FakeStore()
    eng = SessionEngine(FakeClient(), store)
    eng.launch(_cfg())
    assert store.runtime is not None                       # snapshot al lanzar
    p = json.loads(store.runtime)
    assert p["cfg"]["watchlist"] == ["ETH"]
    assert p["cfg"]["limits"]["daily_loss_limit"] == 5.0   # limits COMPLETOS persistidos
    store.runtime = None
    eng.tick(_flat_ms())
    assert store.runtime is not None                       # y en cada tick


def test_rehydrate_restores_session_from_payload():
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.004", "positionValue": "12"}}]
    src = SessionEngine(client, FakeStore())
    src.launch(_cfg())
    src.trend_open.add("ETH"); src.trend_confirmed.add("ETH")
    src.stop_levels["ETH"] = 2940.0; src.stop_oids["ETH"] = 777
    src.state = SessionState.ACTIVE
    payload = src.runtime_payload()

    client2 = FakeClient()
    client2.positions = list(client.positions)
    client2.frontend_orders = [{"coin": "ETH", "oid": 777}]   # el stop sigue vivo
    eng = SessionEngine(client2, FakeStore())
    eng.rehydrate(1, 1234, payload)
    assert eng.state == SessionState.ACTIVE
    assert eng.session_id == 1 and eng.session_started_at == 1234
    assert eng.cfg.watchlist == ["ETH"] and eng.risk is not None
    assert eng.cfg.limits.daily_loss_limit == 5.0
    assert eng.trend_open == {"ETH"} and eng.trend_confirmed == {"ETH"}
    assert eng.stop_oids == {"ETH": 777} and eng.stop_levels == {"ETH": 2940.0}
    assert "ETH" in eng.grids and "ETH" in eng.trends      # estrategias reconstruidas
    assert eng.session_start_value == src.session_start_value


def test_rehydrate_drops_trend_position_closed_while_dead():
    # el stop ejecutó con el bot muerto: la posición ya no está -> fuera de
    # trend_open y su trigger residual cancelado
    client = FakeClient()
    src = SessionEngine(client, FakeStore())
    src.launch(_cfg())
    src.trend_open.add("ETH"); src.trend_confirmed.add("ETH")
    src.stop_levels["ETH"] = 2940.0; src.stop_oids["ETH"] = 777
    payload = src.runtime_payload()

    client2 = FakeClient()                                 # sin posiciones
    eng = SessionEngine(client2, FakeStore())
    eng.rehydrate(1, 1234, payload)
    assert eng.trend_open == set() and eng.trend_confirmed == set()
    assert eng.stop_oids == {} and eng.stop_levels == {}
    assert ("ETH", 777) in client2.canceled_oids           # trigger residual cancelado


def test_rehydrate_forgets_stop_missing_on_exchange():
    # el trigger desapareció (kill parcial, cancelación manual): olvidarlo para
    # que el engine recoloque el stop al siguiente tick, no crea que sigue puesto
    client = FakeClient()
    src = SessionEngine(client, FakeStore())
    src.launch(_cfg())
    src.trend_open.add("ETH")
    src.stop_levels["ETH"] = 2940.0; src.stop_oids["ETH"] = 777
    payload = src.runtime_payload()

    client2 = FakeClient()
    client2.positions = [{"position": {"coin": "ETH", "szi": "0.004", "positionValue": "12"}}]
    client2.frontend_orders = []                           # el stop YA NO existe
    eng = SessionEngine(client2, FakeStore())
    eng.rehydrate(1, 1234, payload)
    assert eng.trend_open == {"ETH"}                       # la posición sí sigue
    assert eng.stop_oids == {} and eng.stop_levels == {}   # stop olvidado -> se recoloca


def test_rehydrate_resumes_closing():
    # un Close en curso sobrevive al reinicio: sigue liquidando hasta quedar plano
    client = FakeClient()
    src = SessionEngine(client, FakeStore())
    src.launch(_cfg())
    src.state = SessionState.CLOSING
    payload = src.runtime_payload()

    client2 = FakeClient()
    client2.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    eng = SessionEngine(client2, FakeStore())
    eng.rehydrate(1, 1234, payload)
    assert eng.state == SessionState.CLOSING
    eng.tick(_flat_ms())
    assert client2.closed == ["ETH"]                       # retoma el cierre activo


def test_rehydrate_keeps_loss_limit_continuity():
    # session_start_value original restaurado: si el límite se cruzó con el bot
    # muerto, el primer tick dispara el auto-close
    client = FakeClient()
    src = SessionEngine(client, FakeStore())
    src.launch(_cfg())                                     # start_value = 40
    payload = src.runtime_payload()

    client2 = FakeClient()
    client2.account_value = "34"                           # -6 <= -5 (daily limit)
    client2.positions = [{"position": {"coin": "ETH", "szi": "0.01", "positionValue": "30"}}]
    eng = SessionEngine(client2, FakeStore())
    eng.rehydrate(1, 1234, payload)
    eng.tick(_flat_ms())
    assert eng.paused is True and eng.state == SessionState.CLOSING


def test_reconcile_batch_records_per_order_errors():
    # el batch devuelve statuses por orden: los rechazos dejan risk_event y no
    # activan la sesión en falso
    class _RejBulk(FakeClient):
        def bulk_place_limits(self, coin, items, post_only=True):
            super().bulk_place_limits(coin, items, post_only)
            return {"status": "ok", "response": {"data": {"statuses": [
                {"error": "Post only order would have immediately matched"}
            ] * len(items)}}}
    client = _RejBulk()
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    assert any(k == "orden_rechazada" for k, _ in store.risk_events)
    assert eng.state == SessionState.SCANNING            # nada colocado de verdad


def test_reconcile_cancels_stale_in_single_batch():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())                       # escalera inicial
    n_orders_before = len(client.orders)
    moved = _flat_ms()
    moved["ETH"].mid = 3000.0 * 1.01
    eng.tick(moved)
    assert client.canceled_oids                # stale cancelados (vía batch)
    assert len(client.orders) > n_orders_before  # y recolocados


def test_toxicity_gate_pulls_quotes_and_cools_down():
    # flujo agresivo unidireccional -> retirar reposo del grid y no cotizar
    # durante el cooldown; al expirar, cotización normal
    client = FakeClient()
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    ms = _flat_ms()
    ms["ETH"].flow_ratio = 0.9
    ms["ETH"].flow_total_usd = 100000.0
    eng.tick(ms)
    assert "ETH" in client.canceled                      # reposo retirado
    assert client.orders == []                           # sin cotizar
    assert eng.toxic_until.get("ETH", 0) > 0
    assert any(a == "cancel" and "toxicity" in r for _, a, r in store.decisions)
    eng.tick(_flat_ms())                                 # tape ya limpio PERO cooldown vivo
    assert client.orders == []
    eng.toxic_until["ETH"] = 0.0                         # cooldown expirado
    eng.tick(_flat_ms())
    assert len(client.orders) > 0                        # vuelve a cotizar


def test_toxicity_gate_ignores_low_volume_noise():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    ms = _flat_ms()
    ms["ETH"].flow_ratio = 0.95
    ms["ETH"].flow_total_usd = 500.0                     # calderilla: no es señal
    eng.tick(ms)
    assert len(client.orders) > 0                        # cotiza normal
    assert eng.toxic_until.get("ETH") is None


def test_engine_has_lock_and_is_free():
    import threading
    eng = SessionEngine(FakeClient(), FakeStore())
    assert isinstance(eng.lock, type(threading.Lock()))
    assert eng.lock.acquire(blocking=False) is True   # libre
    eng.lock.release()


def test_net_delta_cap_blocks_growth_allows_reduction():
    # BTC largo $28 con cap de delta neto $30: un BUY de $10 en ETH aleja de
    # cero (38) -> rechazado; un SELL de $10 acerca (18) -> permitido
    from hlbot.models import Decision, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "BTC", "szi": "0.0005", "positionValue": "28"}}]
    client.account_value = "1000"
    limits = RiskLimits(10.0, 4, 9.0, 50.0, 200.0, 300.0, 30.0)   # max_net_delta=30
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(cfg)

    class _Grid:
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_LIMIT, side=Side.BUY,
                             price=2990.0, size=10.0 / 2990.0, reason="buy rung"),
                    Decision("ETH", ActionType.PLACE_LIMIT, side=Side.SELL,
                             price=3010.0, size=10.0 / 3010.0, reason="sell rung")]
        def half_spread(self, ms, sigma): return 1.0
        def _sigma(self, ms): return 1.0
        def too_toxic(self, ms): return False
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
    buys = [o for o in client.orders if o[1] is True]
    sells = [o for o in client.orders if o[1] is False]
    assert buys == []                                   # bloqueado: alejaría de cero
    assert sells                                        # permitido: reduce |delta|
    assert any("max_net_delta" in d for _, d in store.risk_events)


def test_net_delta_cap_allows_reduction_when_already_over():
    # corto neto -$35 (ya por encima del cap 30): un BUY de $10 REDUCE |delta|
    # a 25 -> debe pasar aunque el estado previo violara el cap
    from hlbot.models import Decision, Side
    client = FakeClient()
    client.positions = [{"position": {"coin": "BTC", "szi": "-0.0006", "positionValue": "35"}}]
    client.account_value = "1000"
    limits = RiskLimits(10.0, 4, 9.0, 50.0, 200.0, 300.0, 30.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                        grid_n=4, grid_range_pct=0.02)
    eng = SessionEngine(client, FakeStore())
    eng.launch(cfg)

    class _Grid:
        def evaluate(self, ms):
            return [Decision("ETH", ActionType.PLACE_LIMIT, side=Side.BUY,
                             price=2990.0, size=10.0 / 2990.0, reason="buy rung")]
        def half_spread(self, ms, sigma): return 1.0
        def _sigma(self, ms): return 1.0
        def too_toxic(self, ms): return False
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
    assert any(o[1] is True for o in client.orders)     # el BUY reductor pasó


# ---------- persistencia enriquecida para análisis de test runs ----------

def test_launch_persists_full_config_json():
    import json
    store = FakeStore()
    eng = SessionEngine(FakeClient(), store)
    eng.launch(_cfg())
    cfg = json.loads(store.config_json)
    assert cfg["watchlist"] == ["ETH"] and cfg["grid_n"] == 4
    assert cfg["limits"]["max_net_delta"] == 1e9          # limits completos
    assert "microprice_weight" in cfg                     # params de micro incluidos


def test_tick_records_micro_snapshot_per_coin():
    store = FakeStore()
    eng = SessionEngine(FakeClient(), store)
    eng.launch(_cfg())
    ms = _flat_ms()
    ms["ETH"].microprice = 3001.5
    ms["ETH"].flow_ratio = 0.4
    ms["ETH"].sigma_px = 2.2
    eng.tick(ms)
    assert len(store.micro) == 1
    row = store.micro[0]
    assert row["coin"] == "ETH" and row["mid"] == 3000.0
    assert row["microprice"] == 3001.5 and row["flow_ratio"] == 0.4
    assert row["toxic"] == 0 and row["inventory"] == 0.0
    eng.tick(_flat_ms())
    assert len(store.micro) == 2                          # una fila por tick y moneda


def test_rich_pnl_snapshot_every_n_ticks():
    from hlbot.session_engine import PNL_SNAPSHOT_EVERY_TICKS
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.004",
                                      "positionValue": "12", "unrealizedPnl": "0.5"}}]
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    for _ in range(PNL_SNAPSHOT_EVERY_TICKS):
        eng.tick(_flat_ms())
    assert len(store.pnl_snapshots) == 1                  # una por minuto de ticks
    pnl, extras = store.pnl_snapshots[0]
    assert pnl == 40.0
    assert extras["unrealized"] == 0.5
    assert extras["gross"] == 12.0 and extras["net_delta"] == 12.0
    assert extras["open_count"] == 1


def test_reconcile_stale_cancel_leaves_tape_trace():
    client = FakeClient()
    store = FakeStore()
    eng = SessionEngine(client, store)
    eng.launch(_cfg())
    eng.tick(_flat_ms())                                  # escalera inicial
    moved = _flat_ms()
    moved["ETH"].mid = 3000.0 * 1.01                      # rungs viejos -> stale
    eng.tick(moved)
    assert any(a == "cancel" and "reconcile" in r for _, a, r in store.decisions)
