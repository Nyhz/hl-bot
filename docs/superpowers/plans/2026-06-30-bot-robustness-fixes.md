# Fixes de robustez del bot — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Que el servidor del bot no se bloquee con el trabajo del tick (bucle fuera del event loop, serializado con un lock) y que cada estrategia gestione solo sus propias posiciones (momentum no cierra/voltea posiciones del grid).

**Architecture:** `SessionEngine.lock` (threading.Lock) serializa toda mutación del engine. El tick se ejecuta vía `asyncio.to_thread` bajo el lock; los endpoints de control mutan el engine bajo el mismo lock; el snapshot del WS lee sin lock (endurecido con try/except). `_decisions_for` rutea por dueño de la posición.

**Tech Stack:** Python 3.14, asyncio, threading, FastAPI/uvicorn, pytest (desde `bot/` con `.venv/bin/python -m pytest`).

## Global Constraints

- Solo cambia el bot (`session_engine.py`, `main.py`, `api.py`). No toca dashboard, riesgo ni estrategias salvo el ruteo de `_decisions_for`.
- El event loop NO debe bloquearse con trabajo del tick: el tick corre en `asyncio.to_thread`.
- Toda **mutación** del engine (tick, launch, close, kill, limits) va bajo `engine.lock`. El **snapshot/lectura** NO toma el lock.
- `_decisions_for`: momentum gestiona solo posiciones en `trend_open`; el grid gestiona el resto del inventario; plano+tendencia → momentum entra; plano+lateral → grid.
- TDD donde sea testeable; el bucle async se verifica con un helper testeable + verificación manual en la revisión.

---

## Task 1: Aislamiento momentum ↔ grid en `_decisions_for`

**Files:**
- Modify: `bot/src/hlbot/session_engine.py` (`_decisions_for`)
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `ms.inventory` (ya lo puebla `tick`), `self.trend_open`, `self.trends[coin].is_trending`.
- Produces: `_decisions_for(ms)` rutea por dueño de la posición.

- [ ] **Step 1: Tests que fallan** — añadir a `bot/tests/test_session_engine.py`:

```python
def test_decisions_grid_position_not_hijacked_by_trend():
    # posición de GRID abierta (inventory>0, NO en trend_open) y régimen de tendencia:
    # debe seguir gestionándola el GRID, no momentum.
    from hlbot.models import MarketState, ActionType
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    class _Trend:
        def is_trending(self, ms): return True
        def evaluate(self, ms):
            from hlbot.models import Decision
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
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py::test_decisions_grid_position_not_hijacked_by_trend -v`
Expected: FAIL (hoy `_decisions_for` rutea por `is_trending` y momentum secuestra la posición del grid → emite el CLOSE).

- [ ] **Step 3: Implementar** — en `session_engine.py`, reemplazar `_decisions_for`:

```python
    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if ms.coin in self.trend_open:        # posición de tendencia -> la gestiona momentum
            return trend.evaluate(ms)
        if abs(ms.inventory) > 1e-12:          # posición de grid abierta -> la gestiona el grid
            return grid.evaluate(ms)           #   (aunque el régimen sea de tendencia)
        if trend.is_trending(ms):              # plano + tendencia -> momentum puede entrar
            return trend.evaluate(ms)
        return grid.evaluate(ms)               # plano + lateral -> grid
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py -v`
Expected: PASS (nuevos + existentes). Si algún test de tendencia existente asumía el ruteo viejo, revisar: los stubs de tendencia que abren posición usan `trend_open` o inventory; confirmar que siguen coherentes.

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "fix(bot): _decisions_for rutea por dueño de la posición (momentum no secuestra el grid)"
```

---

## Task 2: Bucle no bloqueante (engine.lock + to_thread + control bajo lock + snapshot resiliente)

**Files:**
- Modify: `bot/src/hlbot/session_engine.py` (`__init__`: añadir `self.lock`)
- Modify: `bot/src/hlbot/main.py` (`_trade_loop` → `run_tick` + `asyncio.to_thread`)
- Modify: `bot/src/hlbot/api.py` (control endpoints bajo `engine.lock`; `_full_snapshot` con try/except)
- Test: `bot/tests/test_runner.py`, `bot/tests/test_session_engine.py`, `bot/tests/test_api.py`

**Interfaces:**
- Produces: `SessionEngine.lock: threading.Lock`; `main.run_tick(engine, client, store, shared, cache_holder, counters)` (cuerpo del tick síncrono, bajo el lock); `_trade_loop` usa `asyncio.to_thread(run_tick, ...)`.

- [ ] **Step 1: `engine.lock`** — en `session_engine.py`, añadir el import y el atributo. Arriba:

```python
import threading
```
En `__init__`, junto a los demás atributos:
```python
        self.lock = threading.Lock()
```
(No se resetea en `_reset`: es infraestructura, el mismo lock vive toda la vida del engine.)

- [ ] **Step 2: Test del lock + run_tick** — añadir a `bot/tests/test_session_engine.py`:

```python
def test_engine_has_lock_and_is_free():
    import threading
    eng = SessionEngine(FakeClient(), FakeStore())
    assert isinstance(eng.lock, type(threading.Lock()))
    assert eng.lock.acquire(blocking=False) is True   # libre
    eng.lock.release()
```
y a `bot/tests/test_runner.py` (que ya importa de `main`):

```python
def test_run_tick_executes_under_lock_and_releases():
    from hlbot.main import run_tick
    from test_session_engine import FakeClient, FakeStore
    from hlbot.session_engine import SessionEngine
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_run_cfg())                      # ver helper abajo
    shared = {}; cache = {"v": {}}; counters = {"loop": 0, "ticks": 0}
    run_tick(eng, eng.client, eng.store, shared, cache, counters)   # un tick, síncrono
    assert counters["loop"] == 1
    assert eng.lock.acquire(blocking=False) is True   # el lock quedó libre tras el tick
    eng.lock.release()
```
Con un helper local en test_runner.py (watchlist VACÍA: run_tick ejecuta su ciclo + el refresco de
caché —que solo usa `client.user_state`, ya presente en FakeClient— sin tocar velas/persistencia, así
el test es limpio y verifica el ciclo + la liberación del lock sin depender de `Store._conn`):
```python
def _run_cfg():
    from hlbot.models import RiskLimits, SessionConfig
    return SessionConfig(watchlist=[], capital=40.0,
                         limits=RiskLimits(10.0, 4, 2.0, 5.0, 20.0), grid_n=4, grid_range_pct=0.02)
```

- [ ] **Step 3: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_session_engine.py::test_engine_has_lock_and_is_free tests/test_runner.py::test_run_tick_executes_under_lock_and_releases -v`
Expected: FAIL (`run_tick` no existe; `engine.lock` no existe).

- [ ] **Step 4: Implementar `run_tick` + loop en `main.py`** — extraer el cuerpo del tick a `run_tick` (síncrono, bajo el lock) y simplificar `_trade_loop`. Reemplazar la función `_trade_loop` por:

```python
def run_tick(engine, client, store, shared, cache_holder, counters):
    with engine.lock:
        try:
            counters["loop"] += 1
            coins = engine.cfg.watchlist if engine.cfg else []
            now_ms = int(time.time() * 1000)
            funding: dict[str, float] = {}
            if coins:
                try:
                    funding = client.funding_rates()
                except Exception as e:
                    print(f"[trade_loop] funding error: {e}", flush=True)
            states: dict[str, MarketState] = {}
            for coin in coins:
                ms, raw = build_market_state(client, coin, now_ms)
                ms.funding_rate = funding.get(coin)
                states[coin] = ms
                shared[coin] = ms
                persist_candles(store, coin, raw)
            if states:
                engine.tick(states)
                counters["ticks"] += 1
                if counters["ticks"] % PNL_SNAPSHOT_EVERY == 0 and engine.session_id is not None:
                    store.record_pnl_snapshot(engine.session_id, engine._account_value())
            if engine.cfg is not None:
                cache_holder["v"] = refresh_account_cache(
                    client, engine, cache_holder["v"],
                    fetch_extras=(counters["loop"] % ACCOUNT_EXTRAS_EVERY == 0), store=store)
        except Exception as e:  # red caída, BD, etc.: log y seguir
            print(f"[trade_loop] error: {e}", flush=True)


async def _trade_loop(engine: SessionEngine, client: HLClient, store: Store,
                      shared: dict[str, MarketState], cache_holder: dict) -> None:
    counters = {"loop": 0, "ticks": 0}
    while True:
        await asyncio.to_thread(run_tick, engine, client, store, shared, cache_holder, counters)
        await asyncio.sleep(TICK_SECONDS)
```

(El resto de `main.py` —`build_market_state`, `persist_candles`, `refresh_account_cache`, `main()`— no cambia. `main()` sigue llamando `asyncio.create_task(_trade_loop(...))` en el startup.)

- [ ] **Step 5: Endpoints de control bajo el lock + snapshot resiliente en `api.py`**

En cada endpoint de control, envolver la mutación del engine con `with engine.lock:`:
```python
    @app.post("/session/launch")
    def launch(body: LaunchBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        limits_data = body.limits.model_dump()
        limits_data["max_open_positions"] = min(MAX_OPEN_CAP, limits_data["max_open_positions"])
        limits = RiskLimits(**limits_data)
        cfg = SessionConfig(watchlist=body.watchlist, capital=body.capital, limits=limits,
                            grid_n=body.grid_n, grid_range_pct=body.grid_range_pct,
                            adx_threshold=body.adx_threshold)
        try:
            with engine.lock:
                engine.launch(cfg)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"state": engine.state.value}
```
Igual para `close` (`with engine.lock: engine.close()`), `kill` (`with engine.lock: engine.kill(confirm=body.confirm)`), y `/limits` (`with engine.lock: engine.risk.limits = RiskLimits(**body.model_dump())`, manteniendo el chequeo `if engine.risk is None` antes). NO tocar el `/backtest` (usa su propio engine efímero).

Endurecer `_full_snapshot` para que un fallo de lectura no tumbe el WS/servidor:
```python
    def _full_snapshot():
        try:
            snap = engine.snapshot(market_state_provider())
            acc = dict(account_provider())
            fills = acc.pop("_fills", [])
            acc.pop("_funding", None)
            decisions = engine.store.get_decisions(engine.session_id) if engine.session_id else []
            snap["account"] = acc
            snap["positions"] = acc.get("positions", [])
            snap["tape_recent"] = merge_tape(decisions, fills, limit=20)
            return snap
        except Exception as e:
            print(f"[snapshot] error: {e}", flush=True)
            return {"state": getattr(engine.state, "value", "idle"), "paused": engine.paused,
                    "mode": "testnet", "session_id": engine.session_id,
                    "session_started_at": engine.session_started_at,
                    "watchlist": [], "coins": {}, "account": {}, "positions": [], "tape_recent": []}
```

- [ ] **Step 6: Verificar que pasa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (todos). Los tests de control de `test_api.py` siguen pasando (el lock está libre, no bloquea). El nuevo `run_tick`/lock pasan.

- [ ] **Step 7: Commit**

```bash
git add bot/src/hlbot/session_engine.py bot/src/hlbot/main.py bot/src/hlbot/api.py bot/tests/test_session_engine.py bot/tests/test_runner.py
git commit -m "fix(bot): tick en asyncio.to_thread bajo engine.lock; control serializado; snapshot resiliente"
```

---

## Verificación final (en la revisión, manual/integración)

Tras implementar: reiniciar el bot (`launchctl kickstart -k gui/$uid/com.hlbot.app`), lanzar una sesión
testnet (BTC+ETH) y confirmar durante varios minutos que el dashboard se mantiene **LIVE** (no OFFLINE)
y que `/state` responde 200 mientras los ticks colocan/cancelan órdenes. Comprobar el log: sin
`unable to open database file` repetido y sin que el servidor deje de responder.

## Notas de integración (para el revisor)

- El lock es de exclusión simple: si un tick se cuelga en una llamada a HL sin timeout, retiene el lock
  y un control (kill) esperaría a que termine; el servidor sigue vivo (event loop libre). Timeouts por
  llamada al SDK quedan como follow-up (documentado en el spec).
- `_full_snapshot` no toma el lock (lectura); puede ver un estado momentáneamente inconsistente durante
  una mutación — aceptado (cosmético). El try/except evita que tumbe el WS.
- `Store._conn()` abre conexión por operación; usado desde el hilo del tick es thread-safe (cada
  conexión en su hilo). El backtest usa su propio engine/broker y no se ve afectado.
