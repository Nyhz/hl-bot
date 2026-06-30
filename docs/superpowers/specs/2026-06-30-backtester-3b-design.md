# Sub-proyecto 3b — Backtester (lab de parámetros)

**Fecha:** 2026-06-30
**Estado:** diseño aprobado (pendiente de revisión del usuario antes del plan)

## Objetivo

Medir, offline y sin riesgo, si las estrategias actuales (grid Avellaneda-Stoikov + momentum)
ganan o pierden dinero, y permitir **tunear sus parámetros** y ver el efecto. Es el sub-proyecto 3
original ("backtester") y la herramienta de "medir dónde se va el dinero".

**Nota de viabilidad (por la que se eligió esto y no funding carry):** funding carry no es
ejecutable en testnet (de los majors solo BTC tiene par spot, y su precio spot está desconectado
del perp). Queda aparcado para una decisión deliberada de mainnet. El backtester es 100% offline.

## Principio arquitectónico clave

El `SessionEngine` ya está abstraído sobre un objeto `client`. El backtester reutiliza el motor y
las estrategias **tal cual** mediante un **broker simulado** que implementa la misma interfaz que
`HLClient` pero rellena los fills desde velas históricas. Así se prueba el código real (grid A-S +
momentum + guards), no una reimplementación → máxima fidelidad.

## Arquitectura (backend)

### `BacktestBroker` (cliente simulado) — `bot/src/hlbot/backtest/broker.py`
Implementa la interfaz que usa el motor:
`mid(coin)`, `user_state()`, `open_orders(coin)`, `place_limit(...)`, `market_open(...)`,
`market_close(coin)`, `place_stop(...)`, `cancel_all(coin)`, `cancel_order(coin, oid)`,
`set_leverage(...)` (no-op), `funding_rates()`, y un atributo `sz_decimals` (dict).

Estado simulado: caja (`cash` USDC), posición por moneda (`size` firmado, `entry_px`), órdenes
en reposo por moneda (lista de dicts con `oid`, `limitPx`, `sz`, `is_buy`, `reduce_only`, y para
stops `triggerPx`/`is_trigger`), `oid` incremental, precio/funding actuales del paso de replay.

- `mid(coin)` → precio actual del paso (cierre de la vela en curso).
- `user_state()` → sintetiza `assetPositions` (coin, szi, entryPx, positionValue=|size|·mid,
  unrealizedPnl) y `marginSummary.accountValue` = cash + unrealizedPnl. (Formato idéntico al de HL
  para que el motor lo lea sin cambios.)
- `open_orders(coin)` → órdenes en reposo de esa moneda (con `oid`, `limitPx`, `sz`).
- `place_limit(coin, is_buy, price, size, post_only, reduce_only)` → añade orden en reposo (oid
  nuevo). Aplica el mismo redondeo/mín-notional que `HLClient` (reusar `round_price`/`round_size`/
  `meets_min_notional`).
- `market_open(coin, is_buy, size, slippage)` → fill inmediato al `mid` actual con fee taker;
  actualiza posición + caja. Devuelve dict como HL.
- `market_close(coin)` → cierra la posición a `mid` actual con fee taker; realiza PnL.
- `place_stop(coin, is_buy, trigger_px, size, reduce_only)` → añade orden trigger en reposo;
  devuelve `{"resp": ..., "oid": <oid>}` (mismo shape que `HLClient.place_stop` post-3a).
- `cancel_all` / `cancel_order` → eliminan reposo.

### Procesado de una vela — método `step(candle)` del broker
Dada la nueva vela OHLC (y el funding del intervalo):
1. **Fills maker:** para cada orden límite en reposo, llena si la vela cruza el precio:
   compra si `low <= limitPx`, venta si `high >= limitPx`. Fill al `limitPx`, fee **maker 0.015%**.
   Actualiza posición/caja; si `reduce_only`, realiza PnL.
2. **Stops:** trigger de venta (protege largo) salta si `low <= triggerPx`; trigger de compra
   (protege corto) salta si `high >= triggerPx`. Cierra al `triggerPx`, fee **taker 0.045%**.
3. **Funding horario:** en cada cruce de hora, aplica `funding_rate · |posición notional|` a la
   caja (signo: largo paga si funding>0; corto cobra), con el funding **histórico real**.
4. Avanza el precio actual al cierre de la vela.

Constantes de fee como módulo (`MAKER_FEE = 0.00015`, `TAKER_FEE = 0.00045`).

### Runner de replay — `bot/src/hlbot/backtest/runner.py`
`run_backtest(client_data, cfg, coin, candles, funding_series) -> BacktestResult`:
- Crea `BacktestBroker(capital=cfg.capital, sz_decimals=...)` y le fija el precio inicial al cierre
  de `candles[0]` (lo necesita `engine.launch` → `set_anchor`/`mid`). Crea `SessionEngine(broker,
  CaptureStore)` (store en memoria que captura las **decisiones** vía `record_decision`) y hace
  `engine.launch(cfg)`. Las **trades** salen del **log de fills del broker** (no del store).
- Para cada índice `i` de velas: `broker.step(candles[i], funding_i)`; construye
  `MarketState(coin, mid=candles[i].close, candles=candles[:i+1], funding_rate=funding_i)`;
  llama `engine.tick({coin: ms})`; cada N pasos guarda un snapshot de equity (accountValue).
- Al final: `engine.kill(confirm=True)` (cierra posición final a mercado para realizar PnL) y
  computa métricas.

### Datos históricos — `bot/src/hlbot/backtest/data.py`
- `fetch_candles(client, coin, interval, n)` → HL `candleSnapshot` (≤5000), normalizado a `Candle`.
- `fetch_funding(client, coin, start_ms)` → `funding_history`, mapeado a una serie por timestamp;
  para cada vela se toma el funding vigente (último ≤ ts de la vela).

### Métricas — `BacktestResult` (`bot/src/hlbot/backtest/metrics.py`)
Reutiliza la lógica de `track_record` donde aplique. Campos:
`net_pnl, realized_pnl, fees, funding, n_trades, win_rate, max_drawdown, final_equity, start_equity`,
`equity_curve: [{ts, total_pnl}]` (equity absoluta, igual que el live), `trades: [...]` (del log de
fills del broker: coin, dir, price, size, fee, closed_pnl, ts), `decisions: [...]` (del CaptureStore:
ts, coin, action, reason).

### API — `POST /backtest` (en `bot/src/hlbot/api.py`)
- **No coloca órdenes reales** → NO requiere CONTROL_TOKEN. Síncrono.
- Body: `{coin, interval (default "1m"), n_candles (default 1000, máx 5000), capital, grid_n,
  grid_range_pct, skew_strength, spread_vol_mult, adx_threshold, atr_stop_mult,
  max_position_notional, max_coin_notional}` (todos con defaults = los de `SessionConfig`/form).
- Construye `SessionConfig` con esos valores + `RiskLimits` (max_open_positions clamp 4), descarga
  velas+funding, corre `run_backtest`, devuelve el `BacktestResult` como JSON.
- Errores (coin inexistente, sin datos) → 422 con detalle.

## Frontend (dashboard)

- **Nav en la topbar existente:** añadir **BACKTEST** junto a LIVE / HISTORY (en `HeaderBar`), ruta `/backtest`.
- **Página `/backtest`** (`dashboard/app/backtest/page.tsx`):
  - **Formulario "lab"** (`BacktestForm`): selector de moneda (de `/coins`), intervalo, nº de velas,
    capital, y los params editables (grid_n, grid_range_pct, skew_strength, spread_vol_mult,
    adx_threshold, atr_stop_mult, max_position_notional, max_coin_notional). Botón **Run** (spinner mientras corre).
  - **Resultados** (`BacktestResults`): curva de equity (reusar componente de chart de área),
    tiles de métricas (PnL neto, realizado, fees, funding, max drawdown, nº trades, win rate),
    lista de trades, decisiones y panel de atribución (reusar `AttributionPanel` con shape compatible
    o uno análogo).
- `dashboard/lib/api.ts`: `runBacktest(params) -> BacktestResult` (POST a `/backtest` vía el mismo
  proxy `/bot` de Caddy; sin token).
- Tipos en `dashboard/lib/types.ts`: `BacktestResult`, `BacktestParams`.

## Fuera de alcance (v1)
- Multi-moneda por backtest (una moneda por run).
- Persistencia/historial de backtests (efímero: run → ver).
- Comparación A/B lado a lado.
- Funding carry / spot (aparcado).
- Fills parciales, prioridad de cola, slippage avanzado.

## Límites de fidelidad (documentados)
Modelo de fills optimista para maker (una vela que cruza el límite se asume llena del todo, sin
cola ni parciales); sin slippage más allá del modelado. Sirve para **comparar configuraciones**,
no para prometer PnL exacto.

## Pruebas (TDD)
- `BacktestBroker`: place_limit añade reposo; step llena maker al cruzar (compra con low≤px, venta
  con high≥px) y cobra fee; stop salta al cruzar triggerPx; funding horario aplica signo correcto;
  user_state sintetiza posición/equity coherentes; market_open/close realizan PnL con fee taker.
- `runner`: un escenario sintético (velas en rango) produce trades de grid y una curva de equity;
  un escenario en tendencia dispara la rama momentum. Reutiliza el motor real.
- `metrics`: net_pnl = realized + funding − fees (+ unrealized 0 al cierre); max_drawdown correcto
  en una curva conocida.
- `data`: mapeo de funding (último ≤ ts) correcto.
- API: `/backtest` con body válido devuelve estructura con equity_curve/trades/metrics; coin malo → 422.
- Frontend: build + lint + vitest; un test de `runBacktest` (fetch mock) y del render de resultados.

## Decomposición de implementación
- **3b.1 — motor de backtest (backend):** broker + step + runner + data + metrics + endpoint. pytest.
- **3b.2 — panel de backtest (frontend):** nav topbar + página /backtest (form lab + resultados).

## Criterios de aceptación
- Desde la topbar entras a Backtest, configuras moneda/periodo/capital + params, pulsas Run y en
  ~segundos ves equity, métricas, trades y atribución de un backtest que corrió **el código real**
  de las estrategias.
- Cambiar un parámetro (p.ej. grid_n o skew_strength) y re-lanzar cambia los resultados de forma
  coherente.
- Suite del bot verde + dashboard build/lint/test verdes. Sin tocar la ejecución live ni el riesgo.
