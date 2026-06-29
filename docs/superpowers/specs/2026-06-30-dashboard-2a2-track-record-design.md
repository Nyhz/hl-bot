# Diseño: Dashboard 2a.2 — Historial y track record

**Fecha:** 2026-06-30
**Estado:** Diseño aprobado (pendiente de revisión del usuario)
**Contexto:** El núcleo del bot, la API en vivo (2a) y la operacionalización están en `master`. Esta
slice añade **persistencia duradera de fills/funding** y endpoints para ver **el resultado de cada
sesión en detalle** y un **cómputo global de PnL** — separado por modo (testnet vs mainnet). Es
backend; el dashboard (2b) consumirá estos endpoints en una vista "Past Sessions".

## Objetivo
Poder responder, en cualquier momento y aunque Hyperliquid recorte su historial: "¿cómo fue cada
sesión?" (PnL realizado, fees, funding, nº trades, win rate, equity inicial→final, duración) y
"¿cuál es mi track record acumulado?" — **con testnet y mainnet contabilizados por separado** (el
PnL de testnet es ficticio y no debe mezclarse con el real).

## Decisiones tomadas (locked)

| Tema | Decisión |
|------|----------|
| Enfoque | **Derivar** resúmenes al consultar desde datos grabados (no congelar al cerrar) |
| Separación | Cada sesión lleva `mode` (testnet/mainnet); el global se computa **por modo** |
| Persistencia | SQLite (ya en uso); grabar fills/funding duraderos con `session_id` |
| Dedup de fills | Por `tid` (id de trade de Hyperliquid) — no se insertan duplicados |
| Grabación | En el runner, en el refresco de "extras" (reutiliza las llamadas del account_cache) |
| Agregación | Funciones puras testeables (estilo `account.py`) |

## A. Cambios de persistencia (`store.py`)
- **`sessions`**: añadir columna `mode TEXT`. Se fija al crear la sesión (desde `Config`/engine:
  testnet salvo mainnet). `create_session` acepta `mode`.
- **`fills`**: la tabla existe (`id, session_id, ts, coin, side, price, size, fee`) pero está vacía y
  le faltan campos. Añadir `tid TEXT` (único, dedup), `closed_pnl REAL`, `dir TEXT`. Nuevo método
  `record_fill_unique(session_id, tid, ts, coin, side, dir, price, size, fee, closed_pnl)` que hace
  `INSERT OR IGNORE` por `tid` (idempotente). Y `get_fills(session_id)` (ya existe) devuelve los
  campos ampliados.
- **`funding_payments`** (ya existe: `id, session_id, ts, coin, amount`): nuevo
  `record_funding_unique(session_id, key, ts, coin, amount)` con dedup por una clave estable
  (`time+coin`), y `get_funding(session_id) -> list`.
- Nuevos read helpers: `list_sessions(mode=None) -> list[dict]` (filas de `sessions`, opcional por
  modo) y `get_session(session_id) -> dict|None`.

> Migración: el esquema se crea con `CREATE TABLE IF NOT EXISTS`. Para añadir columnas a tablas ya
> existentes (`sessions.mode`, `fills.tid/closed_pnl/dir`), `init_schema` ejecuta `ALTER TABLE ... ADD
> COLUMN` idempotente (envuelto en try/except para tolerar "duplicate column"). Esto preserva los
> datos ya grabados en `bot/data.db`.

## B. Grabación en el runner (`main.py`)
- En el refresco de "extras" (cada N ticks, donde ya se llama a `user_fills`/`user_funding`), y solo
  con sesión activa: insertar los fills nuevos (dedup por `tid`) y los funding nuevos en el store
  con el `session_id` actual. Reutiliza los datos ya traídos (no añade llamadas a Hyperliquid).
- Errores de grabación se loguean y no tumban el bucle.

## C. Funciones puras de agregación (`track_record.py`, nuevo)
- `session_summary(session_row, fills, funding, pnl_snapshots) -> dict`: `{id, mode, started_at,
  ended_at, duration_s, n_trades, realized_pnl, fees, funding, win_rate, equity_start, equity_end}`.
  realized = Σ closed_pnl de fills "Close"; win_rate = wins/closes; equity_start/end de los extremos
  de pnl_snapshots (o capital si no hay).
- `global_stats(sessions_with_summaries) -> dict`: agrega **por modo**:
  `{testnet: {...}, mainnet: {...}}` con `n_sessions, realized_pnl, fees, funding, win_rate,
  best_session, worst_session`.

## D. Endpoints nuevos (`api.py`, lectura, sin token)
- `GET /sessions?mode=` → lista de `session_summary` (orden desc por inicio), filtrable por modo.
- `GET /sessions/{id}` → `{summary, trades: get_fills, equity_curve: get_pnl_snapshots,
  decisions: get_decisions}`.
- `GET /stats/global` → `global_stats` (testnet y mainnet por separado).

## E. Tests
- Store: dedup de `record_fill_unique`/`record_funding_unique` (insertar dos veces el mismo `tid`/key
  → una fila); `list_sessions(mode)`; migración ALTER idempotente (init_schema dos veces no falla).
- Pure: `session_summary` y `global_stats` con fixtures (incluye separación por modo y win_rate).
- API: `/sessions`, `/sessions/{id}`, `/stats/global` con un store real sembrado (varias sesiones de
  ambos modos) → verifican forma, filtro por modo y que testnet/mainnet no se mezclan.
- Runner: la grabación de fills nuevos deduplica por `tid` (test con fake client).

## F. Decomposición
Slice única de backend (este spec). El **2b** añadirá la vista "Past Sessions" (lista + detalle de
sesión + panel de track record global por modo) consumiendo estos endpoints.

## Notas
- No se "congela" el resultado al cerrar: se deriva de los datos grabados, que son la fuente de
  verdad y sobreviven a reinicios y al recorte de historial de Hyperliquid.
- Pendientes heredados (no bloquean): `asyncio.to_thread` en el runner y verificación de `place_stop`
  en testnet antes de mainnet.
