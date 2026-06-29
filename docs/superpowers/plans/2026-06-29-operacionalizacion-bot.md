# Operacionalización del bot (bucle vivo + launchd + xbar): Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el Sub-proyecto 1 atando los 4 huecos del bucle vivo del motor, añadir el proceso runner que ejecuta el tick y sirve la API, y dejarlo arrancable 24/7 en el Mac Mini vía launchd con una entrada de xbar al estilo de las apps existentes.

**Architecture:** Cambios incrementales sobre el paquete `hlbot` ya en `master` (HLClient gana `open_orders`/`place_stop`; SessionEngine gana límites de pérdida con auto-close, reconciliación de órdenes, cancelación de reposo en `close()` y colocación real del stop de tendencia). Un `main.py` nuevo orquesta el bucle de tick + uvicorn. Scripts bash (`hlbot-ctl.sh`, `hlbot-xbar-run.sh`, plist, `trading-status.1m.sh`) replican el patrón calendar/finances/devroom. La lógica determinista se testea con fakes; el runner/SDK/scripts se validan en testnet.

**Tech Stack:** Python 3.11+, `hyperliquid-python-sdk`, `fastapi`+`uvicorn`, `sqlite3`, `pytest`; bash + launchd + xbar (macOS).

## Global Constraints

- Mínimo de orden $10 (reduce-only exento); SIN builder fee; precisión de precio ≤5 sig figs Y ≤(6−szDecimals) decimales (ya implementado en `round_price`/`round_size` — reúsalos, no reimplementes).
- **dev=testnet, prod=mainnet**, arranca en dev. `~/.hlbot/mode` (dev|prod) controla `HL_TESTNET`; `HL_TESTNET=false` solo en prod.
- Límite de pérdida alcanzado → **auto-close** (CLOSING + cancelar reposo, NO liquidar a mercado).
- `daily_pnl` desde **medianoche hora local**; `total_pnl` desde inicio de sesión. Valor de cuenta = `float(user_state()["marginSummary"]["accountValue"])`.
- `close()` cancela órdenes maker en reposo pero NO liquida posiciones (salen por sus stops/range-exit). Es tu semántica de "Close Session".
- Servicio launchd `com.hlbot.app`; API FastAPI en **puerto 3300**; logs en `~/.hlbot/logs/hlbot.log`; URL pública `tradingbot.lan` diferida (el plugin enlaza a `localhost:3300`).
- Secretos solo en `bot/.env` (ya gitignorado). Nunca en scripts ni plugin.
- Estilo xbar: `#!/bin/bash`, PATH Homebrew, colores `#00ff00`/`#ffaa00`/`#ff4444`, glifos `●/○ ✓/✗`, `size=13`, logs `Menlo size=10`, sanitizar líneas (`cut -c1-80 | sed 's/|/∣/g'`).

**Estructura de ficheros (este incremento):**

```
bot/src/hlbot/hl_client.py        # + stop_order_type(), HLClient.open_orders(), HLClient.place_stop()
bot/src/hlbot/session_engine.py   # límites de pérdida, reconciliación, close-cancel, stop real
bot/src/hlbot/main.py             # NUEVO: runner (bucle de tick + uvicorn)
bot/src/hlbot/strategy/trend.py   # SET_STOP lleva size (para colocar el stop real)
bot/tests/test_precision.py       # + test de stop_order_type
bot/tests/test_session_engine.py  # FakeClient extendido + tests de los 4 huecos
bot/tests/test_runner.py          # NUEVO: tests de helpers puros del runner
bot/scripts/hlbot-ctl.sh          # NUEVO
bot/scripts/hlbot-xbar-run.sh     # NUEVO
bot/scripts/com.hlbot.app.plist   # NUEVO (template)
bot/scripts/trading-status.1m.sh  # NUEVO (symlink al dir de plugins de xbar)
```

---

### Task 1: HLClient — `open_orders` y `place_stop`

**Files:**
- Modify: `bot/src/hlbot/hl_client.py`
- Test: `bot/tests/test_precision.py`

**Interfaces:**
- Consumes: `round_price`, `round_size` (ya existen).
- Produces: `stop_order_type(trigger_px: float) -> dict`; `HLClient.open_orders(coin: str) -> list[dict]`; `HLClient.place_stop(coin: str, is_buy: bool, trigger_px: float, size: float, reduce_only: bool = True) -> dict`.

- [ ] **Step 1: Escribir el test que falla** (añadir a `bot/tests/test_precision.py`)

```python
def test_stop_order_type_is_market_sl():
    from hlbot.hl_client import stop_order_type
    ot = stop_order_type(2940.0)
    assert ot["trigger"]["isMarket"] is True
    assert ot["trigger"]["tpsl"] == "sl"
    assert ot["trigger"]["triggerPx"] == 2940.0
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_precision.py::test_stop_order_type_is_market_sl -v`
Expected: FAIL (`ImportError: cannot import name 'stop_order_type'`)

- [ ] **Step 3: Implementar el helper puro + métodos** en `hl_client.py`

Añade el helper puro junto a los otros (antes de los imports del SDK, tras `meets_min_notional`):

```python
def stop_order_type(trigger_px: float) -> dict:
    # Orden trigger stop-loss de mercado (cierra la posición al cruzar triggerPx).
    return {"trigger": {"isMarket": True, "triggerPx": trigger_px, "tpsl": "sl"}}
```

Añade estos dos métodos dentro de la clase `HLClient` (después de `cancel_all`):

```python
    def open_orders(self, coin: str) -> list[dict]:
        return [o for o in self.info.open_orders(self.address) if o.get("coin") == coin]

    def place_stop(self, coin: str, is_buy: bool, trigger_px: float, size: float,
                   reduce_only: bool = True) -> dict:
        szd = self.sz_decimals[coin]
        px = round_price(trigger_px, szd)
        sz = round_size(size, szd)
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        return self.exchange.order(coin, is_buy, sz, px, stop_order_type(px),
                                   reduce_only=reduce_only)
```

> **Verificación SDK (en testnet, Step 6 del plan global):** confirma que `exchange.order` acepta `{"trigger": {...}}` como `order_type` y que pasar `triggerPx` como `limit_px` (4º arg) es correcto para un stop de mercado en la versión instalada del SDK. Ajusta la llamada si difiere, manteniendo la firma pública de `place_stop`.

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd bot && .venv/bin/python -m pytest tests/test_precision.py -v`
Expected: PASS (test nuevo + los 6 anteriores)

- [ ] **Step 5: Extender el test de integración testnet** (añadir a `bot/tests/test_hl_client_testnet.py`, dentro del bloque ya `skipif` sin credenciales)

```python
def test_open_orders_returns_list():
    from hlbot.config import Config
    from hlbot.hl_client import HLClient
    client = HLClient(Config.from_env())
    assert isinstance(client.open_orders("ETH"), list)
```

- [ ] **Step 6: Ejecutar suite (integración se salta sin credenciales)**

Run: `cd bot && .venv/bin/python -m pytest -q`
Expected: todos PASS; integración SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add bot/src/hlbot/hl_client.py bot/tests/test_precision.py bot/tests/test_hl_client_testnet.py
git commit -m "feat(bot): HLClient.open_orders + place_stop (orden trigger)"
```

---

### Task 2: Motor — límites de pérdida con auto-close

**Files:**
- Modify: `bot/src/hlbot/session_engine.py`
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `RiskManager.should_pause` (existe); `client.user_state()`.
- Produces: atributos `session_start_value: float`, `day_anchor_value: float`, `day_anchor_date`; métodos `_account_value() -> float`, `_today_local()`, `_check_loss_limits() -> None`. `tick` llama a `_check_loss_limits()` al inicio.

- [ ] **Step 1: Extender los fakes** (reemplaza las clases `FakeClient` y deja `FakeStore`) en `bot/tests/test_session_engine.py`. Estos campos los usan también las Tasks 3 y 4.

```python
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
```

> `FakeClientWithPosition` (subclase usada por un test existente) sigue funcionando porque solo sobreescribe `user_state`.

- [ ] **Step 2: Escribir los tests que fallan** (añadir a `bot/tests/test_session_engine.py`)

```python
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
```

- [ ] **Step 3: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py::test_loss_limit_triggers_auto_close -v`
Expected: FAIL (`AttributeError` en `paused`/`day_anchor_value` o estado != CLOSING)

- [ ] **Step 4: Implementar** en `session_engine.py`

En `__init__`, añade tras `self.trends = {}`:
```python
        self.session_start_value: float = 0.0
        self.day_anchor_value: float = 0.0
        self.day_anchor_date = None
```

En `launch`, justo antes de `self.paused = False`:
```python
        self.session_start_value = self._account_value()
        self.day_anchor_value = self.session_start_value
        self.day_anchor_date = self._today_local()
```

En `_reset`, añade tras `self.trends = {}`:
```python
        self.session_start_value = 0.0
        self.day_anchor_value = 0.0
        self.day_anchor_date = None
```

Añade estos métodos (p.ej. tras `_open_positions_count`):
```python
    def _account_value(self) -> float:
        state = self.client.user_state()
        return float(state["marginSummary"]["accountValue"])

    def _today_local(self):
        from datetime import datetime
        return datetime.now().astimezone().date()

    def _check_loss_limits(self) -> None:
        if self.risk is None:
            return
        value = self._account_value()
        today = self._today_local()
        if today != self.day_anchor_date:
            self.day_anchor_value = value
            self.day_anchor_date = today
        total_pnl = value - self.session_start_value
        daily_pnl = value - self.day_anchor_value
        pause, reason = self.risk.should_pause(daily_pnl, total_pnl)
        if pause and self.state != SessionState.CLOSING:
            self.store.record_risk_event(self.session_id, "limite", reason)
            self.paused = True
            self.close()
```

En `tick`, añade `self._check_loss_limits()` justo después del guard inicial:
```python
    def tick(self, market_states: dict[str, MarketState]) -> None:
        if self.state == SessionState.IDLE or self.cfg is None:
            return
        self._check_loss_limits()
        n_open = self._open_positions_count()
        ...  # (resto sin cambios en esta tarea)
```

- [ ] **Step 5: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS (todos, incluidos los nuevos)

- [ ] **Step 6: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q   # verde, 2 skips
git add bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "feat(bot): limites de perdida cableados al tick (auto-close)"
```

---

### Task 3: Motor — reconciliación de órdenes y validación de capital

**Files:**
- Modify: `bot/src/hlbot/session_engine.py`
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `client.open_orders(coin)` (Task 1 / FakeClient).
- Produces: `launch` valida `grid_n*10 > capital → ValueError`; `tick` salta rungs con orden en reposo cercana; `_apply(coin, ms, d, n_open, resting_count=0)` con guarda de exposición agregada. Helpers `_resting_prices(coin)`, `_has_resting_near(d, resting, ms)`.

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_session_engine.py`)

```python
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
```

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py::test_launch_rejects_unaffordable_grid tests/test_session_engine.py::test_grid_skips_rungs_with_resting_order -v`
Expected: FAIL (launch no lanza; 2º tick duplica órdenes)

- [ ] **Step 3: Implementar** en `session_engine.py`

En `launch`, añade tras el guard de estado IDLE (antes de `self.cfg = cfg`):
```python
        if cfg.grid_n * 10.0 > cfg.capital:
            raise ValueError(
                f"capital {cfg.capital} insuficiente para grid_n={cfg.grid_n} "
                f"(necesita >= {cfg.grid_n * 10.0})")
```

Añade los helpers (p.ej. tras `_decisions_for`):
```python
    def _resting_prices(self, coin: str) -> list[float]:
        try:
            return [float(o["limitPx"]) for o in self.client.open_orders(coin)]
        except Exception:
            return []

    def _has_resting_near(self, d, resting: list[float], ms: MarketState) -> bool:
        if d.price is None or not resting:
            return False
        step = (2 * self.cfg.grid_range_pct * ms.mid) / self.cfg.grid_n
        tol = step / 2
        return any(abs(r - d.price) <= tol for r in resting)
```

Reemplaza `tick` por (mantiene el `_check_loss_limits` de la Task 2):
```python
    def tick(self, market_states: dict[str, MarketState]) -> None:
        if self.state == SessionState.IDLE or self.cfg is None:
            return
        self._check_loss_limits()
        n_open = self._open_positions_count()
        for coin, ms in market_states.items():
            if coin not in self.grids:
                continue
            resting = self._resting_prices(coin)
            decisions = self._decisions_for(ms)
            for d in decisions:
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                if d.action == ActionType.PLACE_LIMIT and self._has_resting_near(d, resting, ms):
                    continue
                self._apply(coin, ms, d, n_open, len(resting))
        if self.state == SessionState.CLOSING and n_open == 0:
            self._reset()
```

En `_apply`, cambia la firma y añade la guarda de exposición agregada en AMBAS ramas de apertura (no reduce_only). Reemplaza el inicio de cada rama:
```python
    def _apply(self, coin: str, ms: MarketState, d, n_open: int,
               resting_count: int = 0) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            if not d.reduce_only:
                if n_open + resting_count >= self.cfg.limits.max_open_positions:
                    self.store.record_risk_event(self.session_id, "rechazo",
                                                 "exposicion agregada maxima")
                    return
                notional = (d.price or 0) * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_LIMIT requiere side")
            try:
                self.client.place_limit(coin, d.side == Side.BUY, d.price, d.size,
                                        post_only=True, reduce_only=d.reduce_only)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.PLACE_MARKET:
            if not d.reduce_only:
                if n_open + resting_count >= self.cfg.limits.max_open_positions:
                    self.store.record_risk_event(self.session_id, "rechazo",
                                                 "exposicion agregada maxima")
                    return
                notional = ms.mid * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_MARKET requiere side")
            try:
                self.client.place_limit(coin, d.side == Side.BUY, ms.mid, d.size,
                                        post_only=False, reduce_only=d.reduce_only)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            self.client.market_close(coin)
        self.store.record_decision(self.session_id, coin, d.action.value, d.reason)
```

> Nota: la cota agregada se calcula una vez por tick (backstop coarse). La garantía real de exposición ≤ capital la da la validación de `launch` (`grid_n*10 ≤ capital`): la escalera completa (≤ grid_n rungs de $10) cuesta ≤ capital.

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "feat(bot): reconciliacion de ordenes del grid + validacion de capital"
```

---

### Task 4: Motor — `close()` cancela reposo y stop de tendencia real

**Files:**
- Modify: `bot/src/hlbot/session_engine.py`, `bot/src/hlbot/strategy/trend.py`
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `client.cancel_all(coin)`, `client.place_stop(...)`, `client.user_state()`.
- Produces: `close()` cancela reposo por coin; atributos `trend_open: set[str]`, `stops_placed: set[str]`; helper `_position_coins() -> set[str]`; `_apply` no reabre tendencia ya abierta y coloca el stop una sola vez. `TrendOverlayStrategy.evaluate` incluye `size` en las decisiones `SET_STOP`.

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_session_engine.py`)

```python
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
```

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py::test_close_cancels_resting_orders tests/test_session_engine.py::test_trend_stop_placed_once_and_no_reentry -v`
Expected: FAIL (close no cancela; stop no se coloca; reabre)

- [ ] **Step 3: Implementar — `trend.py`** (las decisiones SET_STOP necesitan `size`)

En `bot/src/hlbot/strategy/trend.py`, en `evaluate`, añade `size=self._size(ms.mid)` a las dos decisiones `SET_STOP`. Quedan así (rama alcista y bajista):
```python
                Decision(ms.coin, ActionType.SET_STOP, side=Side.SELL, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="trailing stop ATR"),
```
```python
                Decision(ms.coin, ActionType.SET_STOP, side=Side.BUY, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="trailing stop ATR"),
```

- [ ] **Step 4: Implementar — `session_engine.py`**

En `__init__`, añade tras `self.day_anchor_date = None`:
```python
        self.trend_open: set[str] = set()
        self.stops_placed: set[str] = set()
```

En `launch`, antes de `self.state = SessionState.SCANNING`:
```python
        self.trend_open = set()
        self.stops_placed = set()
```

En `_reset`, añade:
```python
        self.trend_open = set()
        self.stops_placed = set()
```

Reemplaza `close()`:
```python
    def close(self) -> None:
        if self.state in (SessionState.SCANNING, SessionState.ACTIVE):
            self.state = SessionState.CLOSING
            if self.cfg:
                for coin in self.cfg.watchlist:
                    self.client.cancel_all(coin)
```

Añade el helper:
```python
    def _position_coins(self) -> set[str]:
        state = self.client.user_state()
        out: set[str] = set()
        for p in state.get("assetPositions", []):
            coin = p.get("position", {}).get("coin")
            if coin:
                out.add(coin)
        return out
```

En `tick`, justo tras `n_open = self._open_positions_count()`, reconcilia los sets contra posiciones reales:
```python
        open_coins = self._position_coins()
        self.trend_open &= open_coins
        self.stops_placed &= open_coins
```

Reemplaza el método `_apply` COMPLETO por esta versión (añade: no reabrir tendencia ya abierta vía `trend_open`, marcar el coin al abrir a mercado, y colocar el `SET_STOP` real una sola vez vía `stops_placed`):
```python
    def _apply(self, coin: str, ms: MarketState, d, n_open: int,
               resting_count: int = 0) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            if not d.reduce_only:
                if n_open + resting_count >= self.cfg.limits.max_open_positions:
                    self.store.record_risk_event(self.session_id, "rechazo",
                                                 "exposicion agregada maxima")
                    return
                notional = (d.price or 0) * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_LIMIT requiere side")
            try:
                self.client.place_limit(coin, d.side == Side.BUY, d.price, d.size,
                                        post_only=True, reduce_only=d.reduce_only)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.PLACE_MARKET:
            if not d.reduce_only and coin in self.trend_open:
                return
            if not d.reduce_only:
                if n_open + resting_count >= self.cfg.limits.max_open_positions:
                    self.store.record_risk_event(self.session_id, "rechazo",
                                                 "exposicion agregada maxima")
                    return
                notional = ms.mid * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_MARKET requiere side")
            try:
                self.client.place_limit(coin, d.side == Side.BUY, ms.mid, d.size,
                                        post_only=False, reduce_only=d.reduce_only)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if not d.reduce_only:
                self.trend_open.add(coin)
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            self.client.market_close(coin)
        elif d.action == ActionType.SET_STOP:
            if coin not in self.stops_placed and d.side is not None and d.price is not None:
                self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0,
                                       reduce_only=True)
                self.stops_placed.add(coin)
        self.store.record_decision(self.session_id, coin, d.action.value, d.reason)
```

- [ ] **Step 5: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py tests/test_trend.py -v`
Expected: PASS (incluye los de tendencia, que siguen verdes con el `size` añadido)

- [ ] **Step 6: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/session_engine.py bot/src/hlbot/strategy/trend.py bot/tests/test_session_engine.py
git commit -m "feat(bot): close cancela reposo + stop de tendencia real (sin reentrada)"
```

---

### Task 5: Runner (`main.py`)

**Files:**
- Create: `bot/src/hlbot/main.py`
- Test: `bot/tests/test_runner.py`

**Interfaces:**
- Consumes: `Config`, `HLClient`, `Store`, `SessionEngine`, `create_app`, `MarketState`, `Candle`.
- Produces: `candles_to_models(raw: list[dict]) -> list[Candle]`; `build_market_state(client, coin, now_ms) -> tuple[MarketState, list[dict]]`; `persist_candles(store, coin, raw) -> None`; `main() -> None` (orquestación: bucle de tick + uvicorn). Helpers puros testeados offline; `main()` validado en testnet.

- [ ] **Step 1: Escribir los tests que fallan** (`bot/tests/test_runner.py`)

```python
from hlbot.main import candles_to_models, build_market_state
from hlbot.models import Candle

RAW = [{"t": 1, "o": "10", "h": "12", "l": "9", "c": "11", "v": "100"},
       {"t": 2, "o": "11", "h": "13", "l": "10", "c": "12", "v": "120"}]

def test_candles_to_models_maps_fields():
    cs = candles_to_models(RAW)
    assert len(cs) == 2
    assert isinstance(cs[0], Candle)
    assert cs[0].open == 10.0 and cs[0].high == 12.0 and cs[0].close == 11.0
    assert cs[1].t == 2

class _FakeClient:
    def mid(self, coin): return 11.5
    def candles(self, coin, interval, start, end): return RAW

def test_build_market_state():
    ms, raw = build_market_state(_FakeClient(), "ETH", now_ms=999)
    assert ms.coin == "ETH" and ms.mid == 11.5
    assert len(ms.candles) == 2
    assert raw is RAW
```

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.main'`)

- [ ] **Step 3: Implementar `main.py`**

```python
from __future__ import annotations
import asyncio
import time

import uvicorn

from hlbot.config import Config
from hlbot.hl_client import HLClient
from hlbot.store import Store
from hlbot.session_engine import SessionEngine
from hlbot.api import create_app
from hlbot.models import MarketState, Candle

CANDLE_INTERVAL = "1m"
CANDLE_LOOKBACK_MS = 1000 * 60 * 120   # 120 minutos de velas 1m
TICK_SECONDS = 5
PNL_SNAPSHOT_EVERY = 12                 # ~cada minuto a 5s/tick
API_PORT = 3300


def candles_to_models(raw: list[dict]) -> list[Candle]:
    out: list[Candle] = []
    for c in raw:
        out.append(Candle(t=int(c["t"]), open=float(c["o"]), high=float(c["h"]),
                          low=float(c["l"]), close=float(c["c"]), volume=float(c["v"])))
    return out


def build_market_state(client, coin: str, now_ms: int) -> tuple[MarketState, list[dict]]:
    mid = client.mid(coin)
    raw = client.candles(coin, CANDLE_INTERVAL, now_ms - CANDLE_LOOKBACK_MS, now_ms)
    return MarketState(coin=coin, mid=mid, candles=candles_to_models(raw)), raw


def persist_candles(store: Store, coin: str, raw: list[dict]) -> None:
    with store._conn() as conn:
        for c in raw:
            conn.execute(
                "INSERT OR REPLACE INTO market_candles "
                "(coin, interval, t, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (coin, CANDLE_INTERVAL, int(c["t"]), float(c["o"]), float(c["h"]),
                 float(c["l"]), float(c["c"]), float(c["v"])),
            )


async def _trade_loop(engine: SessionEngine, client: HLClient, store: Store,
                      shared: dict[str, MarketState]) -> None:
    ticks = 0
    while True:
        try:
            coins = engine.cfg.watchlist if engine.cfg else []
            now_ms = int(time.time() * 1000)
            states: dict[str, MarketState] = {}
            for coin in coins:
                ms, raw = build_market_state(client, coin, now_ms)
                states[coin] = ms
                shared[coin] = ms
                persist_candles(store, coin, raw)
            if states:
                engine.tick(states)
                ticks += 1
                if ticks % PNL_SNAPSHOT_EVERY == 0 and engine.session_id is not None:
                    store.record_pnl_snapshot(engine.session_id, engine._account_value())
        except Exception as e:  # red caída, etc.: log y seguir
            print(f"[trade_loop] error: {e}", flush=True)
        await asyncio.sleep(TICK_SECONDS)


def main() -> None:
    cfg = Config.from_env()
    client = HLClient(cfg)
    store = Store(cfg.db_path)
    store.init_schema()
    engine = SessionEngine(client, store)
    shared: dict[str, MarketState] = {}

    app = create_app(engine, cfg.control_token, lambda: shared)

    @app.on_event("startup")
    async def _start_loop():
        asyncio.create_task(_trade_loop(engine, client, store, shared))

    uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
```

> `_trade_loop` ejecuta llamadas bloqueantes del SDK dentro del event loop; a 5 s de cadencia y uso local es aceptable. Si la API se nota lenta durante las llamadas, envolver el cuerpo en `await asyncio.to_thread(...)` (mejora futura, no requerida ahora).

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py -v`
Expected: PASS (2)

- [ ] **Step 5: Smoke import del runner** (sin arrancar uvicorn)

Run: `cd bot && .venv/bin/python -c "import hlbot.main; print('ok')"`
Expected: imprime `ok` (sin errores de import)

- [ ] **Step 6: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/main.py bot/tests/test_runner.py
git commit -m "feat(bot): runner main.py (bucle de tick + uvicorn + grabacion de velas)"
```

---

### Task 6: Scripts de operación (ctl + wrapper xbar + launchd)

**Files:**
- Create: `bot/scripts/hlbot-ctl.sh`, `bot/scripts/hlbot-xbar-run.sh`, `bot/scripts/com.hlbot.app.plist`

**Interfaces:**
- Consumes: `bot/.venv/bin/python -m hlbot.main`; mode file `~/.hlbot/mode`; log `~/.hlbot/logs/hlbot.log`.
- Produces: lifecycle `start|stop|restart|dev|prod|install` vía launchctl sobre `com.hlbot.app`; wrapper osascript para xbar.

- [ ] **Step 1: Crear `bot/scripts/hlbot-ctl.sh`**

```bash
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
set -euo pipefail

LABEL="com.hlbot.app"
GUI_DOMAIN="gui/$(id -u)"
REPO="$HOME/dev/hl-bot/bot"
PY="$REPO/.venv/bin/python"
STATE_DIR="$HOME/.hlbot"
MODE_FILE="$STATE_DIR/mode"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/hlbot.log"
PLIST_SRC="$REPO/scripts/com.hlbot.app.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$STATE_DIR" "$LOG_DIR"
[ -f "$MODE_FILE" ] || echo "dev" > "$MODE_FILE"

install_plist() {
  mkdir -p "$HOME/Library/LaunchAgents"
  sed "s#__PY__#${PY}#g; s#__REPO__#${REPO}#g; s#__LOG__#${LOG_FILE}#g" \
    "$PLIST_SRC" > "$PLIST_DST"
  launchctl bootout "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true
  launchctl bootstrap "$GUI_DOMAIN" "$PLIST_DST"
  echo "instalado ${LABEL}"
}

case "${1:-}" in
  start)   launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" ;;
  stop)    launchctl bootout "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  restart) launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" ;;
  dev)     echo "dev"  > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  prod)    echo "prod" > "$MODE_FILE"; launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}" 2>/dev/null || true ;;
  install) install_plist ;;
  *) echo "uso: $0 {start|stop|restart|dev|prod|install}" >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Crear `bot/scripts/hlbot-xbar-run.sh`**

```bash
#!/bin/bash
CMD="$1"
CTL="$HOME/dev/hl-bot/bot/scripts/hlbot-ctl.sh"
osascript -e "do shell script \"'${CTL}' ${CMD}\"" &>/dev/null &
```

- [ ] **Step 3: Crear `bot/scripts/com.hlbot.app.plist`** (template; `__PY__/__REPO__/__LOG__` los sustituye `install`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.hlbot.app</string>
  <key>ProgramArguments</key>
  <array>
    <string>__PY__</string>
    <string>-m</string>
    <string>hlbot.main</string>
  </array>
  <key>WorkingDirectory</key><string>__REPO__</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>__REPO__/src</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__LOG__</string>
  <key>StandardErrorPath</key><string>__LOG__</string>
</dict>
</plist>
```

> El runner lee el modo (testnet/mainnet) desde `~/.hlbot/mode` indirectamente: `Config.from_env` usa `HL_TESTNET`. El `.env` del repo debe poner `HL_TESTNET=true` por defecto; `hlbot-ctl.sh dev/prod` reinicia tras escribir el mode. Para que el mode controle de verdad `HL_TESTNET`, añade al final de `hlbot-ctl.sh dev/prod` (mejora menor, documentada): exportar el flag escribiendo un fichero `.env` derivado o leer el mode en `Config`. **Decisión de implementación:** en `config.py`, si existe `~/.hlbot/mode`, que tenga prioridad sobre `HL_TESTNET` (testnet salvo que el mode sea `prod`). Implementa esto en el Step 4.

- [ ] **Step 4: Hacer que `Config` respete `~/.hlbot/mode`** (Modify `bot/src/hlbot/config.py`)

En `Config.from_env`, antes de construir, determina testnet con prioridad al mode file:
```python
    @classmethod
    def from_env(cls) -> "Config":
        import os.path
        mode_file = os.path.expanduser("~/.hlbot/mode")
        testnet = os.getenv("HL_TESTNET", "true").lower() != "false"
        if os.path.exists(mode_file):
            with open(mode_file) as f:
                testnet = f.read().strip() != "prod"   # prod=mainnet, cualquier otro=testnet
        return cls(
            testnet=testnet,
            account_address=os.getenv("HL_ACCOUNT_ADDRESS") or None,
            secret_key=os.getenv("HL_SECRET_KEY") or None,
            control_token=os.getenv("CONTROL_TOKEN", "change-me"),
            db_path=os.getenv("DB_PATH", "data.db"),
        )
```
Y añade un test en `bot/tests/test_config.py`:
```python
def test_mode_file_prod_forces_mainnet(tmp_path, monkeypatch):
    import os
    home = tmp_path
    (home / ".hlbot").mkdir()
    (home / ".hlbot" / "mode").write_text("prod")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home / ".hlbot" / "mode")
                        if p == "~/.hlbot/mode" else p)
    monkeypatch.delenv("HL_TESTNET", raising=False)
    cfg = Config.from_env()
    assert cfg.testnet is False
```

- [ ] **Step 5: Permisos + verificación de sintaxis**

Run:
```bash
chmod +x bot/scripts/hlbot-ctl.sh bot/scripts/hlbot-xbar-run.sh
bash -n bot/scripts/hlbot-ctl.sh && bash -n bot/scripts/hlbot-xbar-run.sh && echo "sintaxis ok"
cd bot && .venv/bin/python -m pytest tests/test_config.py -v
```
Expected: "sintaxis ok"; tests de config PASS (incluido el nuevo).

- [ ] **Step 6: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/scripts/hlbot-ctl.sh bot/scripts/hlbot-xbar-run.sh bot/scripts/com.hlbot.app.plist bot/src/hlbot/config.py bot/tests/test_config.py
git commit -m "feat(bot): scripts de operacion (ctl + xbar-run + launchd) y mode->testnet/mainnet"
```

---

### Task 7: Plugin xbar (`trading-status.1m.sh`)

**Files:**
- Create: `bot/scripts/trading-status.1m.sh`

**Interfaces:**
- Consumes: launchd `com.hlbot.app`, puerto 3300, SQLite `bot/data.db`, `hlbot-xbar-run.sh`, log `~/.hlbot/logs/hlbot.log`, mode `~/.hlbot/mode`.
- Produces: una entrada de menú-barra con título por estado, digest en vivo desde SQLite, y acciones de ciclo de vida. Se symlinkea al dir de plugins de xbar.

- [ ] **Step 1: Crear `bot/scripts/trading-status.1m.sh`**

```bash
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LABEL="com.hlbot.app"
GUI_DOMAIN="gui/$(id -u)"
XRUN="$HOME/dev/hl-bot/bot/scripts/hlbot-xbar-run.sh"
DB_FILE="$HOME/dev/hl-bot/bot/data.db"
MODE_FILE="$HOME/.hlbot/mode"
LOG_FILE="$HOME/.hlbot/logs/hlbot.log"
PORT=3300

MODE="dev"; [ -f "$MODE_FILE" ] && MODE="$(cat "$MODE_FILE" 2>/dev/null)"
[ "$MODE" = "prod" ] && NET="MAINNET" || NET="TESTNET"

# Servicio
PID="$(launchctl print "${GUI_DOMAIN}/${LABEL}" 2>/dev/null | awk '/pid =/{print $3; exit}')"
RUNNING=false; [ -n "$PID" ] && RUNNING=true

# Health HTTP
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 3 "http://localhost:${PORT}/state" 2>/dev/null)"
HEALTHY=false; { [ "$HTTP_CODE" -ge 200 ] 2>/dev/null && [ "$HTTP_CODE" -lt 500 ] 2>/dev/null; } && HEALTHY=true

# Estado -> glifo + color (mainnet en ámbar para que cante)
if $RUNNING && $HEALTHY; then
  if [ "$MODE" = "prod" ]; then echo "● HL | color=#ffaa00 size=13"; else echo "● HL | color=#00ff00 size=13"; fi
elif $RUNNING; then echo "● HL | color=#ffaa00 size=13"
else echo "○ HL | color=#ff4444 size=13"; fi

echo "---"
echo "Estado: $($RUNNING && echo corriendo || echo parado) | color=white"
echo "Modo: $NET | color=$([ "$MODE" = prod ] && echo '#ffaa00' || echo '#888888')"
[ -n "$PID" ] && echo "PID: $PID | color=#888888"
echo "Puerto: $PORT | color=#888888"

# Digest en vivo (SQLite read-only): última sesión + posiciones/PnL/fees
if [ -f "$DB_FILE" ]; then
  echo "---"
  SID="$(sqlite3 -readonly "$DB_FILE" "SELECT id FROM sessions ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
  if [ -n "$SID" ]; then
    NFILLS="$(sqlite3 -readonly "$DB_FILE" "SELECT COUNT(*) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    FEES="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.4f', COALESCE(SUM(fee),0)) FROM fills WHERE session_id=$SID;" 2>/dev/null)"
    PNL="$(sqlite3 -readonly "$DB_FILE" "SELECT printf('%.2f', total_pnl) FROM pnl_snapshots WHERE session_id=$SID ORDER BY id DESC LIMIT 1;" 2>/dev/null)"
    echo "Sesión #$SID | color=white"
    echo "Fills: ${NFILLS:-0} | color=#888888"
    echo "PnL: ${PNL:-n/d} | color=$([ -n "$PNL" ] && echo '#888888' || echo '#888888')"
    echo "Fees: ${FEES:-0} | color=#888888"
  else
    echo "Sin sesiones aún | color=#888888"
  fi
fi

# Acciones (ciclo de vida)
echo "---"
if $RUNNING; then
  if [ "$MODE" = "dev" ]; then
    echo "Switch to Prod (MAINNET) | bash=$XRUN param1=prod terminal=false refresh=true"
  else
    echo "Switch to Dev (TESTNET) | bash=$XRUN param1=dev terminal=false refresh=true"
  fi
  echo "Restart | bash=$XRUN param1=restart terminal=false refresh=true"
  echo "Stop | bash=$XRUN param1=stop terminal=false refresh=true"
else
  echo "Start | bash=$XRUN param1=start terminal=false refresh=true"
fi

# Caddy + enlaces
echo "---"
CADDY="$(brew services info caddy 2>/dev/null | grep -q 'started' && echo '✓ Caddy' || echo '✗ Caddy')"
echo "$CADDY | color=#888888"
echo "Open dashboard | href=http://localhost:${PORT}"
echo "View Logs | bash=/usr/bin/open param1=-a param2=Terminal param3=$LOG_FILE terminal=false"
```

- [ ] **Step 2: Verificación de sintaxis + prueba del digest con DB sembrada**

Run:
```bash
chmod +x bot/scripts/trading-status.1m.sh
bash -n bot/scripts/trading-status.1m.sh && echo "sintaxis ok"
# Sembrar una DB de prueba y comprobar que el plugin no peta (servicio parado -> rama 'parado')
cd bot && .venv/bin/python -c "from hlbot.store import Store; s=Store('data.db'); s.init_schema(); sid=s.create_session(['ETH'],40.0); s.record_fill(sid,'ETH','buy',3000,0.0034,0.0015); s.record_pnl_snapshot(sid,-0.12)"
bash scripts/trading-status.1m.sh | head -20
```
Expected: "sintaxis ok"; el plugin imprime el título `○ HL` (servicio parado), la sección de estado y el digest con "Sesión #1", "Fills: 1", "PnL: -0.12", "Fees: 0.0015" — sin errores.

- [ ] **Step 3: Symlink al directorio de plugins de xbar** (acción manual, documentada — no commiteable)

Run:
```bash
ln -sf "$HOME/dev/hl-bot/bot/scripts/trading-status.1m.sh" \
  "$HOME/Library/Application Support/xbar/plugins/trading-status.1m.sh"
```
Expected: symlink creado; la entrada aparece en la barra de menú tras refrescar xbar.

- [ ] **Step 4: Commit**

```bash
git add bot/scripts/trading-status.1m.sh
git commit -m "feat(bot): plugin xbar trading-status (estado + digest en vivo)"
```

---

## Checklist de validación en testnet (tras implementar; manual, en el Mac Mini)

1. Crear API wallet de testnet, fondear vía `app.hyperliquid-testnet.xyz/drip`, poner `HL_ACCOUNT_ADDRESS`/`HL_SECRET_KEY`/`CONTROL_TOKEN` en `bot/.env`; `~/.hlbot/mode` = `dev`.
2. `bash bot/scripts/hlbot-ctl.sh install` y `start`; comprobar `curl localhost:3300/state` responde y el log crece.
3. `POST /session/launch` (con `X-Control-Token`) con watchlist `["ETH"]`, capital y límites; ver en `/state` los triggers/condiciones y, en xbar, el digest y el estado.
4. Verificar: el grid no duplica órdenes entre ticks; un `close` cancela el reposo sin liquidar; forzar un límite de pérdida pequeño y ver el auto-close; confirmar que `place_stop` coloca un trigger (validar firma del SDK).
5. Solo tras testnet OK: `hlbot-ctl.sh prod` para mainnet (título ámbar en xbar).
