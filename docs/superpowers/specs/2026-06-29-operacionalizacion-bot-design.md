# Diseño: Operacionalización del bot (bucle vivo + launchd + xbar)

**Fecha:** 2026-06-29
**Estado:** Diseño aprobado (pendiente de revisión del usuario)
**Contexto:** Cierra el Sub-proyecto 1 (`docs/superpowers/specs/2026-06-29-hl-bot-design.md`). El
núcleo (motor, estrategias, riesgo, store, HLClient, API) ya está en `master`. Este incremento
ata los 4 huecos del "bucle vivo" detectados en la revisión final, añade el proceso runner, lo
deja arrancable 24/7 en el Mac Mini vía launchd, y añade una entrada de xbar siguiendo el patrón
de las apps existentes (calendar/finances/devroom).

## Decisiones tomadas (locked)

| Tema | Decisión |
|------|----------|
| Modo dev/prod | **dev=testnet, prod=mainnet**, arranca en dev. `~/.hlbot/mode` controla `HL_TESTNET` |
| Acciones xbar | Solo ciclo de vida: Start/Stop/Restart + Switch Dev/Prod. (Control de sesión → dashboard) |
| Servicio / puerto | launchd `com.hlbot.app`; API FastAPI en **puerto 3300** |
| URL pública | `tradingbot.lan` (Caddy) **diferida** al dashboard; por ahora el plugin enlaza a `localhost:3300` |
| Límite de pérdida alcanzado | **Auto-close**: pasa a CLOSING, cancela órdenes en reposo, deja posiciones a término |
| `daily_pnl` | Medido desde **medianoche hora local** (ancla el valor de cuenta al primer tick del día local) |
| Lenguaje runner | Python (mismo paquete `hlbot`); scripts ops en bash (estilo de las otras apps) |

## A. Correcciones del motor (`bot/src/hlbot/`)

### A.1 Límites de pérdida cableados (`session_engine.py`)
- En `launch`: capturar `session_start_value` = `float(clearinghouseState.marginSummary.accountValue)`
  vía `client.user_state()`; inicializar `day_anchor_value` y `day_anchor_date` (fecha local).
- En `tick` (antes de procesar decisiones): obtener `account_value` actual.
  - Si la fecha local cambió respecto a `day_anchor_date` → re-anclar `day_anchor_value` y fecha.
  - `total_pnl = account_value − session_start_value`; `daily_pnl = account_value − day_anchor_value`.
  - `pause, reason = risk.should_pause(daily_pnl, total_pnl)`.
  - Si `pause` y aún no estaba en CLOSING → registrar `risk_event("limite", reason)`, marcar
    `paused=True`, y ejecutar el **auto-close**: `self.close()` (que ahora cancela reposo, ver A.3).
- `paused` se expone en `snapshot()` (ya lo hace) y, mientras `paused`/CLOSING, no se abren nuevas.

### A.2 Reconciliación de órdenes del grid (`session_engine.py` + `hl_client.py`)
- Nuevo `HLClient.open_orders(coin) -> list[dict]` (filtra `info.open_orders(address)` por coin;
  cada item con al menos `limitPx`, `sz`, `oid`, `side`).
- En `tick`, por par, antes de aplicar decisiones de grid: obtener las órdenes en reposo del coin.
  Para cada `Decision(PLACE_LIMIT)` de un rung, **colocar solo si no hay ya una orden en reposo a
  ese nivel** (precio dentro de ±(spacing/2) del rung). Evita duplicar rungs en cada tick.
- Tope de exposición agregada: no abrir si `(nº posiciones abiertas + nº órdenes en reposo) >=
  max_open_positions` (además del `can_open` por orden ya existente).
- **Validación en `launch`**: si `grid_n * 10.0 > capital` (el capital no sostiene un rung de $10
  por nivel) → `raise ValueError` con mensaje claro. La API lo mapea a 400/409.

### A.3 `close()` cancela reposo, no liquida (`session_engine.py`)
- `close()`: además de pasar a CLOSING, por cada coin de la watchlist `client.cancel_all(coin)`
  (cancela las órdenes maker en reposo que abrirían nueva exposición). **No** llama `market_close`.
- Las posiciones abiertas salen por sus mecanismos naturales (range-exit del grid → CLOSE
  reduce_only; stop ATR de tendencia → trigger en el exchange). Cuando `_open_positions_count()==0`
  → `_reset()` a IDLE (ya implementado).

### A.4 Stop de tendencia real (`hl_client.py` + `session_engine.py`)
- Nuevo `HLClient.place_stop(coin, is_buy, trigger_px, size, reduce_only=True) -> dict`: orden
  trigger stop-loss de mercado (`{"trigger": {"isMarket": True, "triggerPx": <px>, "tpsl": "sl"}}`),
  con `round_price`/`round_size` aplicados; `is_buy` es el lado de la orden de cierre.
- En `_apply`, la rama `SET_STOP` llama `client.place_stop(...)` (en vez de solo registrar).
- Reconciliación: el motor lleva `self.stops_placed: set[str]` (coins con stop ya colocado en la
  sesión), reseteado en `launch`/`_reset`; no recoloca el stop si ya existe para ese coin.

### A.5 Tests
Unitarios con los `FakeClient`/`FakeStore` existentes, extendidos: límite de pérdida → auto-close;
reconciliación (no duplica rungs cuando hay reposo); `launch` rechaza grid no financiable;
`close()` cancela reposo y no liquida; `place_stop` se llama una vez por posición de tendencia;
`HLClient.place_stop`/`open_orders` con tests de precisión/forma (sin red).

## B. Runner (`bot/src/hlbot/main.py`)

Proceso de larga duración:
1. Carga `Config` (modo→`HL_TESTNET`), crea `HLClient`, `Store` (`init_schema`), `SessionEngine`.
2. Mantiene un `dict[str, MarketState]` compartido (último estado por coin).
3. Tarea de fondo (cada ~5 s): para cada coin de la watchlist de la sesión activa, construir
   `MarketState` (mid via `all_mids`; velas 1m via `candles(coin,"1m",...)` mapeadas a `Candle`);
   actualizar el dict; **persistir velas nuevas** en `market_candles`; llamar `engine.tick(states)`;
   cada N ticks, `store.record_pnl_snapshot`. Si no hay sesión activa, el bucle solo refresca mids.
4. Arranca **uvicorn** con `create_app(engine, control_token, market_state_provider)` en `:3300`,
   donde `market_state_provider` devuelve el dict compartido (sin pegar a HL por request).
5. Manejo de errores: excepciones de red en el bucle se loguean y no tumban el proceso.

> Nota: el bucle y uvicorn corren en el mismo proceso (uvicorn + tarea asyncio de fondo).

## C. Operacionalización (estilo calendar/finances/devroom)

- `~/.hlbot/mode` (dev|prod, default dev), `~/.hlbot/logs/hlbot.log`.
- `bot/scripts/hlbot-ctl.sh`: `start|stop|restart|dev|prod|install`. `dev`/`prod` escriben el mode
  y reinician; `install` escribe/recarga el plist. Resuelve el venv del proyecto.
- `bot/scripts/hlbot-xbar-run.sh`: wrapper `osascript` que invoca `hlbot-ctl.sh <cmd>` sin abrir
  Terminal (idéntico patrón a `finances-xbar-run.sh`).
- launchd plist `com.hlbot.app` (template en `bot/scripts/com.hlbot.app.plist`): ejecuta el runner
  con el python del venv, `RunAtLoad`, `KeepAlive`, stdout/err a `~/.hlbot/logs/hlbot.log`,
  `WorkingDirectory` = `bot/`. Lo instala `hlbot-ctl.sh install`.
- Secretos (`HL_SECRET_KEY`, `HL_ACCOUNT_ADDRESS`, `CONTROL_TOKEN`) en `bot/.env` (ya gitignorado).
  El modo prod exige que `.env` tenga credenciales de mainnet; dev usa testnet.

## D. Plugin xbar (`bot/scripts/trading-status.1m.sh`, symlink al dir de plugins)

Clona la plantilla de calendar/finances (bash, `#!/bin/bash`, PATH Homebrew):
- **Título:** `● HL` por estado — healthy-dev `#00ff00`; **healthy-prod (mainnet) `#ffaa00`** (que
  cante que estás con dinero real); starting `#ffaa00`; crashed `#ff4444`; stopped `○ #ff4444`.
- **Estado:** Status / Mode (TESTNET|MAINNET) / Uptime / PID / Port 3300.
- **Digest en vivo (SQLite, read-only):** de la última sesión — estado (IDLE/SCANNING/ACTIVE/
  CLOSING), nº posiciones abiertas, PnL de sesión, fees acumuladas. (Consulta directa al `data.db`
  del bot, como finances lee su `finances.db`.)
- **Acciones:** Start/Stop/Restart + Switch Dev/Prod (vía `$XRUN` = `hlbot-xbar-run.sh`).
- **Caddy + enlaces:** estado de `brew services info caddy`; "Open dashboard" →
  `http://localhost:3300` (luego `tradingbot.lan`); "View Logs" → abre el log en Terminal.
- Sanitiza líneas (`cut -c1-80 | sed 's/|/∣/g'`).

## Estrategia de testing y validación
- Correcciones del motor + nuevos métodos de HLClient: tests unitarios (sin red).
- Runner, ctl, plist y plugin: validación manual en testnet en el Mac Mini (faucet
  `app.hyperliquid-testnet.xyz/drip`, API wallet en `.env`), siguiendo un checklist en el plan.
- Mainnet (prod) solo tras validar en testnet; el color ámbar del título recuerda el modo real.
