# Diseño: Dashboard 2b — Frontend Next.js (MICRO-DEGEN TERMINAL)

**Fecha:** 2026-06-30
**Estado:** Aprobado para ejecución autónoma (el usuario delegó los gates; se construyen las 4 slices seguidas)
**Contexto:** Todo el backend (2a + 2a.2) está en `master`: la API del bot en `:3300` sirve datos en
vivo (REST + WebSocket enriquecido) e historial. Este sub-proyecto construye el frontend visual —el
"MICRO-DEGEN TERMINAL"— que el usuario quiere: dark/neón, monoespaciado, denso, game-y. Consume SOLO
la API del bot. La estética y los paneles ya se acordaron en `2026-06-30-dashboard-design.md`; este
spec fija la **capa de datos**, el **control con token-proxy**, la **decomposición en 4 slices** y la
**estrategia de verificación**.

## Stack y convenciones
- **Next.js (App Router) + React + TypeScript + Tailwind CSS.** Lightweight-Charts (gráficos),
  Framer Motion (animaciones), sonner (toasts + sonido). Vitest para tests de lógica pura.
- **Estética:** tema dark, fuente monoespaciada, paleta neón (verde `#00ff88`, rojo `#ff4466`,
  ámbar `#ffaa00`, muted `#8a8f98`), glow. Tokens de color/tipografía en CSS variables + config Tailwind.
- **Frontend puro:** solo habla con la API del bot (REST + WS). NO toca Hyperliquid ni la BD.

## Configuración (`dashboard/.env.local`, en .gitignore)
- `NEXT_PUBLIC_BOT_HTTP=http://localhost:3300` y `NEXT_PUBLIC_BOT_WS=ws://localhost:3300/ws` (cliente).
- `BOT_API_URL=http://localhost:3300` y `CONTROL_TOKEN=<el de bot/.env>` (servidor; para el proxy de control).

## Arquitectura de datos
- **`lib/types.ts`**: tipos TS que reflejan los payloads de la API (Snapshot, Account, Position,
  Condition, Trigger, Candle, TapeEvent, SessionSummary, GlobalStats).
- **`lib/api.ts`**: cliente REST (fetch) → `getCandles(coin)`, `getEquityCurve(sessionId)`, `getCoins()`,
  `getSessions(mode?)`, `getSession(id)`, `getStatsGlobal()`, `getTape()`. Base = `NEXT_PUBLIC_BOT_HTTP`.
- **`lib/useLiveSnapshot.ts`**: hook que abre el WebSocket (`NEXT_PUBLIC_BOT_WS`), mantiene el último
  snapshot enriquecido, reconecta con backoff si se cae, y expone `{snapshot, connected}`. Es la fuente
  del estado vivo (state, mode, account, positions, coins{mid,triggers,conditions,armed}, tape_recent,
  session_id, session_started_at).
- **Control (proxy server-side)**: rutas `app/api/control/launch|close|kill|limits/route.ts` (route
  handlers de Next.js) que leen `CONTROL_TOKEN` del entorno del servidor, añaden `X-Control-Token` y
  reenvían a `BOT_API_URL`. El navegador llama a `/api/control/...` → el token nunca llega al cliente.

## Gotchas del contrato 2a/2a.2 (a respetar en el frontend)
- `pnl_snapshots.total_pnl` y `/equity_curve` contienen **equity absoluta** (no PnL): se grafican como
  **curva de equity**. El **PnL neto de sesión** está en `session_summary.net_pnl` (delta de equity).
- Las posiciones traen `mark_px=null`: el frontend usa el **mid vivo** de `snapshot.coins[coin].mid`
  para entry→mark/PnL visual. No hay `opened_at` (la edad solo se muestra si se puede derivar).
- `mode` top-level del snapshot = `testnet`/`mainnet` → badge (naranja/verde). El track record global
  separa por modo (no mezclar).

## Decomposición (4 slices, en orden; cada una su plan→implementación→merge)
1. **2b.1 — Cimientos:** scaffold Next.js+TS+Tailwind, tema dark/neón + fuente mono, `lib/types.ts`,
   `lib/api.ts`, `lib/useLiveSnapshot.ts`, rutas proxy de control, y una página mínima que muestre en
   vivo: badge de estado + modo + `● LIVE` + EQUITY (de `account.equity`). Prueba el flujo contra `:3300`.
2. **2b.2 — Terminal en vivo:** `HeaderBar`, `EquityHero` + `EquityCurve` (área), `StatTiles`
   (OPEN/WIN/REALIZED/FEES/FUNDING), `OpenPositions` (filas + sparkline), `Tape`; `FocusChart`
   (candlestick + líneas de triggers/EMAs/entrada/liq del par enfocado) y `Watchlist` (gauges de
   condiciones + estado ARMED). Layout grid tiled.
3. **2b.3 — Control + estímulo:** `LaunchPanel` (form launch con watchlist de `/coins`, capital,
   límites, params), botones Close/Kill (con confirmación) vía el proxy; toasts sonner + sonido al
   abrir/cerrar posición (detectado por diffs del snapshot); number-tickers, pulsos/glow, transiciones.
4. **2b.4 — Past Sessions:** lista de sesiones (filtro por modo) + detalle de sesión (trades, curva de
   equity, decisiones) + panel de **track record global por modo** (`/stats/global`).

## Estrategia de verificación (autónoma)
- **Lógica pura** (formateadores, mapeo snapshot→props, diffs para toasts, construcción de series de
  chart): tests Vitest.
- **Cada slice debe pasar**: `npm run build` (typecheck + compilación) y `npm run lint` limpios, y los
  tests Vitest verdes. Esto es lo que se garantiza de forma autónoma.
- **Verificación visual** (render real, animaciones, conexión WS con datos en vivo): se valida con el
  usuario en pantalla al despertar; el bot corre en `:3300` (testnet) para conectar. Los planes dejan
  el dev server listo (`npm run dev`).

## Notas
- Pendientes pre-mainnet heredados (no bloquean el frontend): `asyncio.to_thread` en el runner y
  verificar `place_stop` en testnet.
- Decisiones de diseño visual delegadas al asistente (el usuario duerme); se siguen la estética y los
  paneles ya acordados, dejando el pulido fino para revisión posterior.
