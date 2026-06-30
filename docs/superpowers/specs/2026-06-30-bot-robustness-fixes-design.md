# Fixes de robustez del bot: bucle no bloqueante + aislamiento momentum/grid

**Fecha:** 2026-06-30
**Estado:** diseño aprobado por el usuario (enfoque confirmado, incl. snapshot sin lock).

## Contexto

Durante una sesión en vivo en testnet el servidor del bot (`uvicorn` :3300) dejó de responder
(`/state` → 000) mientras el log repetía `unable to open database file`; el dashboard quedó OFFLINE
y la posición quedó sin gestionar (se recuperó a mano). Causa de fondo: el **bucle de trading corre
en el event loop** y hace **llamadas síncronas a Hyperliquid** por tick; bajo carga / una llamada
lenta o colgada, **bloquea el servidor entero**. Además se observó una interacción no deseada:
la **rama de momentum cerró a mercado una posición que había abierto el grid** y la volteó.

Dos fixes, solo en el bot (no toca dashboard ni riesgo/estrategia salvo el ruteo):

## Fix 1 — Bucle de trading no bloqueante

**Objetivo:** que el event loop (uvicorn + WebSocket) **no se bloquee nunca** con el trabajo del tick,
de modo que el servidor/dashboard sigan vivos aunque una llamada a HL tarde o se cuelgue.

**Diseño:**
- **`SessionEngine.lock`**: un `threading.Lock` (nuevo atributo en `__init__`) que serializa todo
  acceso de **escritura/mutación** al engine.
- **Tick fuera del event loop**: en `main.py`, `_trade_loop` ejecuta el cuerpo del tick con
  `await asyncio.to_thread(run_tick)`. `run_tick` adquiere `engine.lock` durante toda su ejecución
  (construir market states, `engine.tick`, persistencia de velas/PnL/fills, refresco de la caché de
  cuenta). El bucle queda: `while True: await asyncio.to_thread(run_tick); await asyncio.sleep(TICK_SECONDS)`.
- **Endpoints de control** (`/session/launch`, `/session/close`, `/session/kill`, `/limits`): ya son
  `def` síncronos (FastAPI los corre en su threadpool, fuera del loop), pero mutan el engine →
  **envuelven su mutación en `with engine.lock:`** para serializar con el tick (sin carreras
  tick↔control). El event loop no se bloquea (el endpoint vive en un hilo del pool).
- **Snapshot del WS / `/state`** (solo lectura): **NO toman el lock** (heartbeat a 1s pase lo que
  pase). `_full_snapshot` se **endurece con try/except** para que un fallo de lectura (p.ej. BD)
  devuelva un snapshot mínimo en vez de tumbar el WS/servidor. Se acepta una inconsistencia visual
  rarísima y momentánea (es lectura, no dinero).

**Fuera de alcance (follow-up):** timeouts por llamada al SDK de HL (si una llamada se cuelga, el
hilo del tick se queda esperando y el lock no se libera → el bot deja de tradear pero **el servidor
sigue vivo**, que es la mejora clave; un kill esperaría al tick en vuelo). Se documenta como pendiente.

**Persistencia:** el bucle ya envuelve el tick en try/except (loguea y sigue). Con el tick en un hilo
y conexiones SQLite por operación (`Store._conn()` abre conexión por llamada, thread-safe si cada
conexión se usa en su hilo), los fallos de BD no tumban el servidor.

## Fix 2 — Aislamiento momentum ↔ grid

**Objetivo:** que cada estrategia gestione **solo las posiciones que abrió ella**; que momentum no
cierre/voltee a mercado una posición abierta por el grid.

**Diseño:** reescribir `SessionEngine._decisions_for(ms)` (usa `ms.inventory`, ya poblado por `tick`):
```
trend = self.trends[ms.coin]; grid = self.grids[ms.coin]
if ms.coin in self.trend_open:        # posición de tendencia -> la gestiona momentum
    return trend.evaluate(ms)
if abs(ms.inventory) > 1e-12:          # hay posición de grid abierta -> la gestiona el grid
    return grid.evaluate(ms)           #   (aunque el régimen sea de tendencia)
if trend.is_trending(ms):              # plano + tendencia -> momentum PUEDE entrar
    return trend.evaluate(ms)
return grid.evaluate(ms)               # plano + lateral -> grid
```
Nota: con esto, una posición abierta por el grid se queda en el grid aunque `is_trending` salte; el
`#4 regime-cancel` (cancelar grid en reposo al entrar en tendencia) ya está condicionado a
`coin not in trend_open` — sigue igual; el grid re-coloca su escalera cuando el régimen vuelve a lateral.

## Pruebas

- **Fix 2 (testeable):** en `test_session_engine.py`, un test que con `ms.inventory>0` (posición de
  grid, coin NO en `trend_open`) y `is_trending` True (stub) → `_decisions_for` devuelve decisiones
  de **grid** (no un CLOSE/PLACE_MARKET de momentum). Y que con `coin in trend_open` → momentum;
  con plano+trending → momentum (entrada).
- **Fix 1 (parcialmente testeable):**
  - `engine.lock` existe y es un lock reentrante-no (Lock simple).
  - Test de que los endpoints de control adquieren el lock: usar un FakeEngine/instrumentación que
    registre adquisición, o testear un helper `with_engine_lock(engine, fn)`. Si es difícil aislar,
    testear el comportamiento serializado con un lock real (un hilo "tick" que mantiene el lock y un
    control que espera).
  - El bucle `_trade_loop` con `asyncio.to_thread`: extraer el cuerpo del tick a una función
    `run_tick(...)` testeable (sin asyncio) y testear que ejecuta un tick (con FakeClient) sin error.
  - **Verificación final (manual/integración, en la revisión):** reiniciar el bot, lanzar una sesión
    testnet y confirmar que el dashboard **NO** pasa a OFFLINE durante la sesión (el heartbeat sigue).
- Suite del bot verde (`.venv/bin/python -m pytest`).

## Criterios de aceptación

- Con una sesión activa, el servidor responde y el dashboard se mantiene **LIVE** (sin OFFLINE) aunque
  los ticks hagan muchas llamadas a HL.
- Momentum nunca cierra/voltea a mercado una posición abierta por el grid (verificado por test).
- Sin carreras tick↔control que corrompan el estado del engine (serializado por `engine.lock`).
- Suite del bot verde.
