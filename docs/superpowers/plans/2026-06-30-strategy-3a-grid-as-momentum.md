# Sub-proyecto 3a — Grid A-S + funding y Momentum mejorado — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescribir el grid al estilo Avellaneda-Stoikov (precio de referencia que se re-centra con el inventario + spread por volatilidad + sesgo por funding) y mejorar el momentum (entrada estricta, trailing stop, salida por reversión), sin tocar el launch ni el tamaño fijo de $10.

**Architecture:** Las estrategias (`GridStrategy`, `TrendOverlayStrategy`) son puras: reciben un `MarketState` (con `mid`, `candles`, `funding_rate` y nuevo `inventory`) y devuelven `Decision`s. El motor (`SessionEngine`) puebla `inventory`, reconcilia la escalera del grid (cancela stale por `oid` + coloca faltantes) y gestiona el trailing stop (cancela+recoloca el trigger). La volatilidad sale del ATR ya existente.

**Tech Stack:** Python 3.14, pytest, hyperliquid-python-sdk, pandas/numpy (indicadores). Tests en `bot/tests/`, ejecutar con `.venv/bin/python -m pytest` desde `bot/`.

## Global Constraints

- Cada orden de grid y cada entrada de tendencia tiene notional = `max_position_notional` (default **$10**, mínimo de Hyperliquid). El tamaño NO se deriva de A-S.
- Órdenes de grid SIEMPRE maker/post-only (TIF "Alo"). Entradas de tendencia market (IOC, `market_open`).
- Todos los guards de riesgo intactos: leverage real, `max_coin_notional`, 4 posiciones simultáneas (clamp en API), límites de pérdida → auto-close.
- Un solo modo de sesión (grid+tendencia con conmutación por ADX por moneda). NO se toca el launch/dashboard en 3a.
- TDD: test que falla → implementación mínima → test pasa → commit. Suite completa verde antes de cada commit final de tarea.
- Ejecutar tests siempre desde `bot/` con `.venv/bin/python -m pytest`.

---

## File Structure

- `bot/src/hlbot/models.py` — añadir `MarketState.inventory`; añadir campos A-S a `SessionConfig`; quitar `grid_spacing_pct` (sin uso).
- `bot/src/hlbot/strategy/grid.py` — **reescritura** a Avellaneda-Stoikov + funding (pura).
- `bot/src/hlbot/strategy/trend.py` — entrada estricta + gestión en-posición (trailing/exit).
- `bot/src/hlbot/hl_client.py` — `cancel_order(coin, oid)`; `place_stop` devuelve `oid`.
- `bot/src/hlbot/session_engine.py` — poblar `inventory`; reconciliar escalera del grid; trailing stop; mantener tendencia mientras haya posición.
- `bot/tests/test_grid.py`, `bot/tests/test_trend.py`, `bot/tests/test_session_engine.py` — tests nuevos/actualizados.

---

## Task 1: `MarketState.inventory` poblado por el motor

**Files:**
- Modify: `bot/src/hlbot/models.py` (dataclass `MarketState`)
- Modify: `bot/src/hlbot/session_engine.py` (`tick`)
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Produces: `MarketState.inventory: float` (tamaño firmado de la posición; + largo / − corto). El motor lo setea en cada tick antes de llamar a las estrategias.

- [ ] **Step 1: Test que falla** — añadir a `bot/tests/test_session_engine.py`:

```python
def test_tick_populates_inventory_from_user_state():
    client = FakeClient()
    client.positions = [{"position": {"coin": "ETH", "szi": "0.0064", "positionValue": "10.1"}}]
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    ms = _flat_ms()
    eng.tick(ms)
    assert abs(ms["ETH"].inventory - 0.0064) < 1e-9
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py::test_tick_populates_inventory_from_user_state -v`
Expected: FAIL (`inventory` no existe o queda en 0.0).

- [ ] **Step 3: Implementar** — en `models.py`, añadir el campo a `MarketState`:

```python
@dataclass
class MarketState:
    coin: str
    mid: float
    candles: list[Candle] = field(default_factory=list)
    funding_rate: float | None = None
    inventory: float = 0.0
```

En `session_engine.py`, dentro de `tick`, añadir el cálculo de tamaños firmados y poblar `inventory`. Tras el bloque que calcula `pos_notionals`/`equity`/`gross`, añadir:

```python
        pos_sizes = {}
        for p in asset_positions:
            pos = p.get("position", {}) or {}
            coin = pos.get("coin")
            if coin:
                pos_sizes[coin] = float(pos.get("szi", 0) or 0)
```

Y dentro del bucle `for coin, ms in market_states.items():`, justo después de `if coin not in self.grids: continue`, añadir:

```python
            ms.inventory = pos_sizes.get(coin, 0.0)
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/models.py bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "feat(3a): MarketState.inventory poblado por el motor cada tick"
```

---

## Task 2: Parámetros A-S en `SessionConfig`

**Files:**
- Modify: `bot/src/hlbot/models.py` (dataclass `SessionConfig`)
- Test: `bot/tests/test_models.py`

**Interfaces:**
- Produces: nuevos campos de `SessionConfig` con defaults: `skew_strength=1.5`, `spread_vol_mult=0.5`, `min_spread_frac=0.001`, `funding_tilt=0.3`, `funding_min=0.00005`, `ema_sep_frac=0.001`. Se elimina `grid_spacing_pct`. `grid_range_pct` (0.02 default) pasa a significar "clamp de rango máximo del grid respecto a la referencia".

- [ ] **Step 1: Test que falla** — añadir a `bot/tests/test_models.py`:

```python
def test_sessionconfig_has_as_defaults():
    from hlbot.models import SessionConfig, RiskLimits
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0,
                        limits=RiskLimits(10.0, 4, 2.0, 5.0, 20.0))
    assert cfg.skew_strength == 1.5
    assert cfg.spread_vol_mult == 0.5
    assert cfg.min_spread_frac == 0.001
    assert cfg.funding_tilt == 0.3
    assert cfg.funding_min == 0.00005
    assert cfg.ema_sep_frac == 0.001
    assert not hasattr(cfg, "grid_spacing_pct")
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_models.py::test_sessionconfig_has_as_defaults -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** — en `models.py`, reemplazar el bloque de campos de `SessionConfig` (quitando `grid_spacing_pct`, añadiendo los A-S):

```python
@dataclass
class SessionConfig:
    watchlist: list[str]
    capital: float
    limits: RiskLimits
    grid_n: int = 10
    grid_range_pct: float = 0.03        # clamp de rango máximo del grid respecto a la referencia
    ema_fast: int = 9
    ema_slow: int = 21
    adx_period: int = 14
    adx_threshold: float = 25.0
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    # Avellaneda-Stoikov + funding
    skew_strength: float = 1.5
    spread_vol_mult: float = 0.5
    min_spread_frac: float = 0.001
    funding_tilt: float = 0.3
    funding_min: float = 0.00005
    ema_sep_frac: float = 0.001
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/models.py bot/tests/test_models.py
git commit -m "feat(3a): parámetros A-S en SessionConfig; quitar grid_spacing_pct"
```

---

## Task 3: `GridStrategy` Avellaneda-Stoikov + funding (rewrite)

**Files:**
- Modify (rewrite): `bot/src/hlbot/strategy/grid.py`
- Test: `bot/tests/test_grid.py`

**Interfaces:**
- Consumes: `SessionConfig` (campos A-S de Task 2), `MarketState.inventory` (Task 1), `hlbot.indicators.atr`.
- Produces: `GridStrategy(cfg)` con `set_anchor(mid)` (compat), `reservation_price(ms, sigma)`, `half_spread(ms, sigma)`, `desired_prices(ms) -> list[float]`, `evaluate(ms) -> list[Decision]`, `armed_triggers(ms)`, `conditions(ms)`. Cada rung es un `Decision(PLACE_LIMIT, side, price, size=max_position_notional/price)`.

- [ ] **Step 1: Tests que fallan** — reemplazar el contenido de `bot/tests/test_grid.py` por:

```python
from hlbot.models import MarketState, Candle, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.grid import GridStrategy

def _cfg(**kw):
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02, **kw)

def _candles(vol=10.0, n=40, base=3000.0):
    # velas con rango ~vol para que ATR ~ vol
    return [Candle(t=i, open=base, high=base + vol, low=base - vol, close=base, volume=1.0)
            for i in range(1, n + 1)]

def _ms(mid=3000.0, inventory=0.0, funding=None, vol=10.0):
    return MarketState(coin="ETH", mid=mid, candles=_candles(vol=vol), funding_rate=funding,
                       inventory=inventory)

def test_reservation_equals_mid_when_flat():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    sigma = g._sigma(ms)
    assert abs(g.reservation_price(ms, sigma) - ms.mid) < 1e-9

def test_reservation_below_mid_when_long():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.005)   # largo
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) < ms.mid

def test_reservation_above_mid_when_short():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=-0.005)
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) > ms.mid

def test_half_spread_grows_with_volatility():
    g = GridStrategy(_cfg())
    lo = g.half_spread(_ms(vol=5.0), g._sigma(_ms(vol=5.0)))
    hi = g.half_spread(_ms(vol=40.0), g._sigma(_ms(vol=40.0)))
    assert hi > lo

def test_funding_positive_targets_short_reservation():
    # funding positivo (largos pagan) y estando flat -> objetivo corto -> referencia > mid
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0, funding=0.001)
    sigma = g._sigma(ms)
    assert g.reservation_price(ms, sigma) > ms.mid

def test_evaluate_rungs_are_ten_dollars_and_dont_cross_mid():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    ds = [d for d in g.evaluate(ms) if d.action == ActionType.PLACE_LIMIT]
    assert ds
    for d in ds:
        assert abs(d.price * d.size - 10.0) < 1e-6
        if d.side == Side.BUY:
            assert d.price < ms.mid
        else:
            assert d.price > ms.mid

def test_evaluate_emits_only_place_limit_rungs():
    g = GridStrategy(_cfg())
    ms = _ms(inventory=0.0)
    ds = g.evaluate(ms)
    assert ds and all(d.action == ActionType.PLACE_LIMIT for d in ds)  # grid no cierra por precio
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_grid.py -v`
Expected: FAIL (API nueva no existe).

- [ ] **Step 3: Implementar** — reemplazar **todo** `bot/src/hlbot/strategy/grid.py` por:

```python
from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)
from hlbot.indicators import atr


class GridStrategy:
    """Grid estilo Avellaneda-Stoikov: precio de referencia que se re-centra con el
    inventario, spread proporcional a la volatilidad (ATR) y sesgo por funding."""

    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.anchor: float | None = None

    def set_anchor(self, mid: float) -> None:
        # Compat con launch(); A-S no usa ancla fija, pero guardamos el mid de arranque.
        self.anchor = mid

    def _sigma(self, ms: MarketState) -> float:
        closes = [c.close for c in ms.candles]
        highs = [c.high for c in ms.candles]
        lows = [c.low for c in ms.candles]
        if len(closes) < self.cfg.atr_period + 1:
            return 0.0
        return atr(highs, lows, closes, self.cfg.atr_period)[-1]

    def _phi_target(self, ms: MarketState) -> float:
        # Fracción objetivo de inventario (de max_coin_notional) según funding.
        f = ms.funding_rate
        if f is None or abs(f) < self.cfg.funding_min:
            return 0.0
        return -(1.0 if f > 0 else -1.0) * self.cfg.funding_tilt

    def reservation_price(self, ms: MarketState, sigma: float) -> float:
        cap = self.cfg.limits.max_coin_notional
        q_notional = ms.inventory * ms.mid
        phi = max(-1.0, min(1.0, q_notional / cap)) if cap > 0 else 0.0
        e = phi - self._phi_target(ms)
        return ms.mid - e * self.cfg.skew_strength * sigma

    def half_spread(self, ms: MarketState, sigma: float) -> float:
        return max(self.cfg.min_spread_frac * ms.mid, self.cfg.spread_vol_mult * sigma)

    def _rung_size(self, price: float) -> float:
        return self.cfg.limits.max_position_notional / price

    def _ladder(self, ms: MarketState) -> tuple[float, list[tuple[float, Side]]]:
        sigma = self._sigma(ms)
        res = self.reservation_price(ms, sigma)
        h = self.half_spread(ms, sigma)
        rungs: list[tuple[float, Side]] = []
        if h <= 0:
            return res, rungs
        max_dist = self.cfg.grid_range_pct * res
        for i in range(1, self.cfg.grid_n + 1):
            buy = res - i * h
            sell = res + i * h
            if buy < ms.mid and (res - buy) <= max_dist:
                rungs.append((buy, Side.BUY))
            if sell > ms.mid and (sell - res) <= max_dist:
                rungs.append((sell, Side.SELL))
        return res, rungs

    def desired_prices(self, ms: MarketState) -> list[float]:
        _, rungs = self._ladder(ms)
        return [p for p, _ in rungs]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        # Sin range-exit por precio: con re-centrado la referencia sigue al mid, así que
        # esa salida quedaría muerta. La protección es el cap de inventario
        # (max_coin_notional, bloquea crecimiento) + los límites de pérdida de sesión (auto-close).
        sigma = self._sigma(ms)
        res = self.reservation_price(ms, sigma)
        _, rungs = self._ladder(ms)
        out: list[Decision] = []
        for price, side in rungs:
            out.append(Decision(ms.coin, ActionType.PLACE_LIMIT, side=side,
                                price=price, size=self._rung_size(price),
                                reason=f"grid rung {price:.4f} (res {res:.2f})"))
        return out

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        _, rungs = self._ladder(ms)
        return [Trigger(ms.coin, p, s, "place_limit",
                        f"{'compra' if s == Side.BUY else 'venta'} maker en {p:.4f}")
                for p, s in rungs]

    def conditions(self, ms: MarketState) -> list[Condition]:
        sigma = self._sigma(ms)
        res = self.reservation_price(ms, sigma)
        max_dist = self.cfg.grid_range_pct * res
        _, rungs = self._ladder(ms)
        return [
            Condition("en_rango", abs(ms.mid - res), max_dist, abs(ms.mid - res) <= max_dist),
            Condition("rungs_activos", float(len(rungs)), 1.0, len(rungs) > 0),
        ]
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_grid.py -v`
Expected: PASS.

- [ ] **Step 5: Verificar que el resto sigue verde** (la firma de `GridStrategy` cambió; el motor aún usa `evaluate`/`armed_triggers`/`conditions`, que siguen existiendo).

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (todos). Si algún test del motor asumía la API vieja del grid (`set_anchor` sigue existiendo), ajustarlo mínimamente.

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/strategy/grid.py bot/tests/test_grid.py
git commit -m "feat(3a): grid Avellaneda-Stoikov (reservation + spread vol + sesgo funding)"
```

---

## Task 4: `cancel_order` + reconciliar la escalera del grid en el motor

**Files:**
- Modify: `bot/src/hlbot/hl_client.py` (`cancel_order`)
- Modify: `bot/src/hlbot/session_engine.py` (reconciliación grid en `tick`)
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `GridStrategy.desired_prices(ms)` (Task 3); `client.open_orders(coin)` (devuelve dicts con `limitPx` y `oid`); `client.cancel_order(coin, oid)`.
- Produces: el motor, para órdenes de grid, cancela las que no estén a tolerancia `tol = step/2` de ningún precio deseado y coloca las deseadas que falten.

- [ ] **Step 1: Tests que fallan** — añadir a `bot/tests/test_session_engine.py`. Antes, ampliar `FakeClient` para registrar cancelaciones por oid y devolver oids en `open_orders`:

```python
# en FakeClient.__init__ añadir:
        self.canceled_oids = []
        self._next_oid = 1000
# en FakeClient añadir métodos:
    def cancel_order(self, coin, oid):
        self.canceled_oids.append((coin, oid))
    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        self._next_oid += 1
        self.orders.append((coin, is_buy, price, size, reduce_only, post_only))
        self.resting.append({"coin": coin, "limitPx": price, "sz": size, "oid": self._next_oid})
        return {"status": "ok"}
```

(Nota: el `open_orders` de `FakeClient` ya devuelve `self.resting`; ahora cada entrada lleva `oid`.)

```python
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
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py::test_grid_reconcile_cancels_stale_and_places_missing tests/test_session_engine.py::test_grid_reconcile_no_churn_when_unchanged -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** — en `hl_client.py`, añadir tras `cancel_all`:

```python
    def cancel_order(self, coin: str, oid: int) -> None:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        self.exchange.cancel(coin, oid)
```

En `session_engine.py`, sustituir el bloque del bucle de `tick` que decide órdenes de grid por una reconciliación. Reemplazar la parte:

```python
            decisions = self._decisions_for(ms)
            for d in decisions:
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                if d.action == ActionType.PLACE_LIMIT and self._has_resting_near(d, resting, ms):
                    continue
                self._apply(coin, ms, d, n_open, equity, gross,
                            pos_notionals.get(coin, 0.0))
```

por:

```python
            decisions = self._decisions_for(ms)
            grid_active = (coin not in self.trend_open
                           and not self.trends[coin].is_trending(ms))
            if grid_active and self.state != SessionState.CLOSING:
                self._reconcile_grid(coin, ms, decisions, n_open, equity, gross,
                                     pos_notionals.get(coin, 0.0))
            for d in decisions:
                if d.action == ActionType.PLACE_LIMIT:
                    continue  # los PLACE_LIMIT de grid los gestiona _reconcile_grid
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                self._apply(coin, ms, d, n_open, equity, gross,
                            pos_notionals.get(coin, 0.0))
```

Y añadir el método de reconciliación (recibe los valores de riesgo ya calculados en `tick`; usa `step = half_spread`, tolerancia `step/2`):

```python
    def _reconcile_grid(self, coin, ms, decisions, n_open, equity, gross, coin_notional) -> None:
        desired = [(d.price, d) for d in decisions if d.action == ActionType.PLACE_LIMIT]
        grid = self.grids[coin]
        tol = max(grid.half_spread(ms, grid._sigma(ms)) / 2.0, 1e-9)
        open_orders = self.client.open_orders(coin)
        # 1) cancelar stale: órdenes en reposo lejos de cualquier precio deseado
        for o in open_orders:
            px = float(o.get("limitPx", 0) or 0)
            oid = o.get("oid")
            if oid is None:
                continue
            if not any(abs(px - dp) <= tol for dp, _ in desired):
                self.client.cancel_order(coin, oid)
        # 2) colocar las deseadas que no tengan ya una orden cerca (guards vía _apply/_risk_ok)
        rest_px = [float(o.get("limitPx", 0) or 0) for o in open_orders]
        for dp, d in desired:
            if any(abs(dp - rp) <= tol for rp in rest_px):
                continue
            self._apply(coin, ms, d, n_open, equity, gross, coin_notional)
```

El guard de leverage/cap se mantiene correcto porque `_apply` recibe el `gross` y `coin_notional` reales calculados en `tick` (no recalculados aquí).

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS. Revisar que `test_grid_skips_rungs_with_resting_order` (si sigue existiendo) se sustituye por los dos nuevos de reconciliación; eliminar el viejo si choca con la nueva lógica.

- [ ] **Step 5: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/hl_client.py bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "feat(3a): reconciliación de la escalera del grid (cancel stale por oid + place faltantes)"
```

---

## Task 5: Momentum — entrada más estricta

**Files:**
- Modify: `bot/src/hlbot/strategy/trend.py` (`_signals`, `is_trending`, y callers)
- Test: `bot/tests/test_trend.py`

**Interfaces:**
- Consumes: `cfg.ema_sep_frac` (Task 2), `cfg.adx_threshold`, `MarketState`.
- Produces: `is_trending(ms)` devuelve True solo si `ADX>umbral` **y** `ADX` creciente **y** separación de EMAs `> ema_sep_frac`. `_signals(ms)` devuelve `(ef, es, adx_now, adx_prev, atr_)`.

- [ ] **Step 1: Tests que fallan** — añadir a `bot/tests/test_trend.py`:

```python
def _weak_cross_candles(n=60):
    # EMAs casi pegadas: precio plano con micro-pendiente -> separación < umbral
    out = []
    for i in range(1, n + 1):
        c = 100.0 + i * 0.001
        out.append(Candle(t=i, open=c, high=c + 0.05, low=c - 0.05, close=c, volume=1.0))
    return out

def test_entry_rejected_when_emas_too_close():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=100.0, candles=_weak_cross_candles())
    assert s.is_trending(ms) is False
```

(El test existente `test_is_trending_true_in_strong_uptrend` debe seguir pasando: en una subida fuerte, ADX alto + creciente + EMAs separadas.)

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_trend.py -v`
Expected: el nuevo test FALLA (hoy `is_trending` solo mira ADX>umbral).

- [ ] **Step 3: Implementar** — en `trend.py`, reemplazar `_signals` e `is_trending`:

```python
    def _signals(self, ms: MarketState):
        closes = [c.close for c in ms.candles]
        highs = [c.high for c in ms.candles]
        lows = [c.low for c in ms.candles]
        ef = ema(closes, self.cfg.ema_fast)[-1]
        es = ema(closes, self.cfg.ema_slow)[-1]
        adx_series = adx(highs, lows, closes, self.cfg.adx_period)
        adx_now = adx_series[-1]
        adx_prev = adx_series[-2] if len(adx_series) >= 2 else 0.0
        atr_ = atr(highs, lows, closes, self.cfg.atr_period)[-1]
        return ef, es, adx_now, adx_prev, atr_

    def is_trending(self, ms: MarketState) -> bool:
        if len(ms.candles) < self.cfg.ema_slow:
            return False
        ef, es, adx_now, adx_prev, _ = self._signals(ms)
        sep = abs(ef - es) / ms.mid if ms.mid else 0.0
        return (adx_now > self.cfg.adx_threshold
                and adx_now > adx_prev
                and sep > self.cfg.ema_sep_frac)
```

Actualizar los demás métodos que desempaquetan `_signals` (en `conditions`, `armed_triggers`, `evaluate`) para el nuevo arity de 5 elementos: cambiar `ef, es, adx_, _ = self._signals(ms)` por `ef, es, adx_, adx_prev, _ = self._signals(ms)` y `ef, es, _, atr_ = ...` por `ef, es, _, _, atr_ = ...` según corresponda. (La lógica de esos métodos no cambia en esta tarea; solo el desempaquetado.)

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_trend.py -v`
Expected: PASS (nuevo + existentes).

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/strategy/trend.py bot/tests/test_trend.py
git commit -m "feat(3a): momentum entrada estricta (ADX creciente + separación EMAs)"
```

---

## Task 6: Momentum — trailing stop y salida por reversión

**Files:**
- Modify: `bot/src/hlbot/strategy/trend.py` (`evaluate`)
- Modify: `bot/src/hlbot/hl_client.py` (`place_stop` devuelve `oid`)
- Modify: `bot/src/hlbot/session_engine.py` (`_decisions_for`, manejo de `SET_STOP` con trailing)
- Test: `bot/tests/test_trend.py`, `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `MarketState.inventory` (Task 1); `hlbot.indicators.atr` en el motor para el umbral de trailing.
- Produces: `TrendOverlayStrategy.evaluate(ms)` gestiona el caso "en posición": emite `CLOSE` al recruce de EMA y `SET_STOP` con el stop trailing deseado; sin reentrada. El motor mantiene la rama de tendencia mientras `coin in trend_open`, y para `SET_STOP` cancela+recoloca el trigger solo cuando el stop mejora ≥ `0.1*ATR`.

- [ ] **Step 1: Tests que fallan** — añadir a `bot/tests/test_trend.py`:

```python
def test_evaluate_closes_on_ema_reversal_when_long():
    s = TrendOverlayStrategy(_cfg())
    # tendencia bajista (ef<es) pero inventario LARGO -> debe cerrar
    candles = _downtrend_candles()
    ms = MarketState(coin="ETH", mid=1.0, candles=candles, inventory=0.004)
    actions = [d.action for d in s.evaluate(ms)]
    assert ActionType.CLOSE in actions

def test_evaluate_emits_trailing_stop_when_in_position():
    s = TrendOverlayStrategy(_cfg())
    candles = _uptrend_candles()
    ms = MarketState(coin="ETH", mid=60.0, candles=candles, inventory=0.004)  # largo en alza
    ds = s.evaluate(ms)
    assert any(d.action == ActionType.SET_STOP and d.side == Side.SELL for d in ds)
    assert all(d.action != ActionType.PLACE_MARKET for d in ds)   # no reabre
```

Y a `bot/tests/test_session_engine.py` (trailing monótono en el motor):

```python
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
```

(El umbral de mejora `0.1*ATR`: con velas planas `_flat_ms` el ATR ~1, así que 2950−2940=10 supera 0.1; 2945<2950 empeora y no toca.)

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_trend.py tests/test_session_engine.py -v`
Expected: FAIL en los nuevos.

- [ ] **Step 3: Implementar — `place_stop` devuelve oid.** En `hl_client.py`, cambiar el final de `place_stop` para devolver el `oid`:

```python
        resp = self.exchange.order(coin, is_buy, sz, limit, stop_order_type(trig),
                                   reduce_only=reduce_only)
        try:
            st = resp["response"]["data"]["statuses"][0]
            oid = (st.get("resting") or st.get("filled") or {}).get("oid")
        except (KeyError, IndexError, TypeError):
            oid = None
        return {"resp": resp, "oid": oid}
```

En `FakeClient` (tests): que `place_stop` devuelva un oid incremental y lo registre:

```python
    def place_stop(self, coin, is_buy, trigger_px, size, reduce_only=True):
        self._next_oid += 1
        self.stops.append((coin, is_buy, trigger_px, size, reduce_only))
        return {"resp": {"status": "ok"}, "oid": self._next_oid}
```

- [ ] **Step 4: Implementar — `trend.evaluate` con gestión en-posición.** Reemplazar `evaluate` en `trend.py`:

```python
    def evaluate(self, ms: MarketState) -> list[Decision]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, adx_now, adx_prev, atr_ = self._signals(ms)
        if abs(ms.inventory) > 0:
            long = ms.inventory > 0
            # salida por reversión
            if (long and ef < es) or (not long and ef > es):
                return [Decision(ms.coin, ActionType.CLOSE, reduce_only=True,
                                 reason="reversión de tendencia (recruce EMA)")]
            # trailing stop deseado
            if long:
                stop = ms.mid - self.cfg.atr_stop_mult * atr_
                side = Side.SELL
            else:
                stop = ms.mid + self.cfg.atr_stop_mult * atr_
                side = Side.BUY
            return [Decision(ms.coin, ActionType.SET_STOP, side=side, price=stop,
                             size=abs(ms.inventory), reduce_only=True, reason="trailing stop ATR")]
        # flat: entrada solo si la tendencia está confirmada (is_trending filtra todo)
        if not self.is_trending(ms):
            return []
        if ef > es:
            stop = ms.mid - self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.BUY,
                         size=self._size(ms.mid), reason="tendencia alcista (ADX>umbral, EMA fast>slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.SELL, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="stop inicial ATR"),
            ]
        if ef < es:
            stop = ms.mid + self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.SELL,
                         size=self._size(ms.mid), reason="tendencia bajista (ADX>umbral, EMA fast<slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.BUY, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="stop inicial ATR"),
            ]
        return []
```

- [ ] **Step 5: Implementar — motor: mantener tendencia en posición + trailing.** En `session_engine.py`:

(a) En `__init__` y `_reset`, añadir `self.stop_levels: dict[str, float] = {}` y `self.stop_oids: dict[str, int] = {}` (y limpiarlos en `_reset`).

(b) Cambiar `_decisions_for` para no soltar la tendencia mientras haya posición de tendencia abierta:

```python
    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if ms.coin in self.trend_open or trend.is_trending(ms):
            return trend.evaluate(ms)
        return grid.evaluate(ms)
```

(c) Reemplazar el manejo de `SET_STOP` en `_apply` por la lógica de trailing (cancela+recoloca solo si mejora ≥ `0.1*ATR`):

```python
        elif d.action == ActionType.SET_STOP:
            if d.side is None or d.price is None:
                return
            from hlbot.indicators import atr as _atr
            closes = [c.close for c in ms.candles]
            highs = [c.high for c in ms.candles]
            lows = [c.low for c in ms.candles]
            atr_ = _atr(highs, lows, closes, self.cfg.atr_period)[-1] if len(closes) > self.cfg.atr_period else 0.0
            thr = max(0.1 * atr_, 1e-9)
            cur = self.stop_levels.get(coin)
            is_long_stop = (d.side == Side.SELL)   # stop de venta protege un largo
            if cur is None:
                res = self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0, reduce_only=True)
                self.stop_levels[coin] = d.price
                self.stop_oids[coin] = res.get("oid")
                self.stops_placed.add(coin)
            else:
                improves = (d.price > cur + thr) if is_long_stop else (d.price < cur - thr)
                if improves:
                    old = self.stop_oids.get(coin)
                    if old is not None:
                        self.client.cancel_order(coin, old)
                    res = self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0, reduce_only=True)
                    self.stop_levels[coin] = d.price
                    self.stop_oids[coin] = res.get("oid")
```

(d) En la limpieza por posición desaparecida (`gone`), olvidar también el stop: donde hoy se hace `self.stops_placed -= gone`, añadir:

```python
        for c in gone:
            self.stop_levels.pop(c, None)
            self.stop_oids.pop(c, None)
```

- [ ] **Step 6: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_trend.py tests/test_session_engine.py -v`
Expected: PASS.

- [ ] **Step 7: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (todos).

- [ ] **Step 8: Commit**

```bash
git add bot/src/hlbot/strategy/trend.py bot/src/hlbot/hl_client.py bot/src/hlbot/session_engine.py bot/tests/test_trend.py bot/tests/test_session_engine.py
git commit -m "feat(3a): momentum trailing stop + salida por reversión; motor mantiene tendencia en posición"
```

---

## Notas de integración (para el revisor final)

- El `_apply` de `SET_STOP` antiguo usaba `self.stops_placed` para colocar una sola vez; ahora `stops_placed` sigue marcando "stop inicial puesto" pero el trailing vive en `stop_levels`/`stop_oids`. Verificar que la entrada de tendencia (que emite PLACE_MARKET + SET_STOP en el mismo tick) coloca el stop inicial una vez y que los ticks siguientes (en posición) lo van mejorando.
- La reconciliación del grid sustituye a `_has_resting_near`; si queda algún uso de `_has_resting_near`, puede eliminarse o dejarse sin uso (YAGNI: eliminarlo).
- `set_anchor` queda como compat (lo llama `launch`); no participa en la lógica A-S.
- El dashboard NO se toca en 3a: las `conditions` del grid cambian de nombre (`en_rango`, `rungs_activos`) pero el front las renderiza genéricamente.
