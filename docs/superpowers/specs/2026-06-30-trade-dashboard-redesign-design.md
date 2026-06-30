# Rediseño del Trade dashboard

**Fecha:** 2026-06-30
**Estado:** diseño aprobado (pendiente de revisión del usuario antes del plan)

## Objetivo

Rediseñar la vista LIVE (Trade) para que: (1) ocupe **100vw×100vh sin scroll de página**,
aprovechando el hueco para gráficas más grandes; (2) ponga **las posiciones abiertas en el centro**,
cada una en un slot con su gráfica + datos + las próximas decisiones del bot encima; (3) saque la
configuración de lanzamiento a un **modal** (no visible en todo momento). Es solo frontend (consume
la API/WS que ya existe); no cambia el bot ni el riesgo.

## Layout (100vw × 100vh, sin scroll de página)

Columna vertical que llena la altura; los paneles internos hacen scroll si hace falta.

1. **Topbar** (fina, fija): marca `NYHZ // MICRO-DEGEN TERMINAL`, nav (LIVE/HISTORY/BACKTEST),
   modo (TESTNET/MAINNET) + estado de conexión (● LIVE/○ OFFLINE) + edad/estado de sesión, y a la
   **derecha los controles de sesión** (Launch idle / Close+Kill activa — ver más abajo).
2. **Banda superior** (a lo ancho): a la izquierda **Session P&L** (equity grande + PnL de sesión
   con %), a su lado su **gráfica de equity**; a la derecha los **stats** de la sesión en cards
   (open/win/realized/fees/funding) + atribución (realizado/funding/fees/neto). Reusa `EquityHero`,
   `EquityCurve`, `StatTiles`, `AttributionPanel`.
3. **Zona central (protagonista)**: grid **adaptativo** de posiciones abiertas (`TradeGrid`),
   ocupa toda la altura restante. Reparto por número de posiciones:
   - **0** → estado idle: "sin posiciones abiertas · vigilando N pares" (el watchlist de la
     derecha muestra los candidatos).
   - **1** → un `TradeSlot` ocupa toda la zona.
   - **2** → dos slots (mitad y mitad).
   - **3-4** → grid 2×2 (con 3, la 4ª celda queda vacía).
4. **Columna derecha** (raíl): **Watchlist** (pares con condiciones/ARMED) arriba + **Tape**
   (decisiones/fills) abajo, con scroll interno.

## `TradeSlot` (una posición abierta)

Reutiliza y amplía `FocusChart`:
- **Gráfica de velas** del par con las **price-lines de las próximas decisiones del bot encima**
  (rungs del grid / stop de tendencia) — ya las dibuja `FocusChart` desde `coins[coin].triggers`.
- **Cabecera de datos**: par · LONG/SHORT (color) · leverage · entrada → mark · **open PnL** ($ y %) ·
  liq · notional. Usa `positionView` y el `mid` vivo de `coins[coin].mid`.
- **Tira de condiciones**: las gauges de armado de ese par (`coins[coin].conditions` vía `Gauge`),
  para ver qué falta para la próxima decisión.

El `mark`/PnL salen del snapshot vivo (WS); `mark_px` viene `null` del backend → se usa el `mid` de
`coins[coin]` (contrato 2a→2b ya existente).

## Launch (modal) y controles de sesión

Los controles viven en la **derecha de la topbar**, condicionados al estado de sesión:
- **IDLE** → botón **[▶ Launch session]** que abre `LaunchModal`: overlay oscuro centrado con el
  formulario de configuración actual (los campos de `LaunchPanel`: chips de pares, capital, grid_n,
  posición $ (max_position_notional), max lev, cap moneda $ (max_coin_notional), adx umbral, pérdida
  diaria/total; nota fija "máx 4 posiciones simultáneas"). Cierre por **X / Esc / click en el overlay**.
  Al lanzar con éxito (`/api/control/launch` → 200) el modal se cierra; si error, se muestra el toast
  actual y el modal permanece.
- **SCANNING/ACTIVE/CLOSING** → en su lugar, los dos botones de `SessionControls`:
  - **Close session** (`/api/control/close`): bloquea nuevas y deja cerrar las abiertas de forma natural.
  - **Kill switch** (`/api/control/kill` con confirmación): cierra todo al instante.
  (Se mantiene el proxy server-side con CONTROL_TOKEN; el frontend no cambia ese contrato.)

`LaunchModal` no añade dependencias: overlay con `position: fixed`, fondo semitransparente, panel
centrado, cierre con click en el fondo y `keydown` Escape. **Reutiliza el `LaunchPanel` existente**
renderizándolo dentro del modal (no se re-extrae el formulario); a `LaunchPanel` se le añade una prop
opcional `onLaunched?: () => void` que dispara tras un launch con éxito para que el modal se cierre.
`LaunchPanel` ya muestra solo el formulario cuando la sesión está idle, así que el modal solo se ofrece
en idle.

## Componentes

- **Modificar** `dashboard/app/page.tsx`: relayout completo (banda + `TradeGrid` + raíl), 100vh.
- **Modificar** `dashboard/components/HeaderBar.tsx`: añadir a la derecha el botón Launch (idle) o
  `SessionControls` (activa), según `snapshot.state`.
- **Crear** `dashboard/components/TradeGrid.tsx`: recibe `positions`, `coins`; elige el reparto por
  número de posiciones y renderiza un `TradeSlot` por posición (idle si 0).
- **Crear** `dashboard/components/TradeSlot.tsx`: cabecera de datos + `FocusChart` (con triggers) +
  tira de condiciones, para un par/posición.
- **Crear** `dashboard/components/LaunchModal.tsx`: overlay + cierre (X/Esc/click-fondo) que renderiza
  el `LaunchPanel` existente dentro.
- **Modificar** `dashboard/components/LaunchPanel.tsx`: añadir prop opcional `onLaunched?: () => void`
  que se llama tras un launch con éxito (para cerrar el modal). Sin otros cambios de comportamiento.
- **Reusar**: `EquityHero`, `EquityCurve`, `StatTiles`, `AttributionPanel`, `Watchlist`, `Tape`,
  `SessionControls`, `FocusChart`, `Gauge`, `positionView`, `NumberTicker`.
- **CSS** (`globals.css`): clases de layout a pantalla completa — `.app-100vh` (grid/flex column,
  `height: 100vh; overflow: hidden`), `.top-band`, `.center-stage`, `.right-rail` (scroll interno),
  y el grid adaptativo `.trade-grid[data-n]` (1 / 2 / 2×2). Responsive: por debajo de ~1024px se
  permite scroll vertical y las regiones se apilan (no romper en pantallas pequeñas).

## Lógica pura (testeable)

- `slotLayout(n: number)`: 0→"idle", 1→"one", 2→"two", 3|4→"grid" (clase/data-attr del grid).
- `slotItems(positions, coins)`: ordena las posiciones para los slots de forma estable (p.ej. por
  coin alfabético) → array de hasta 4 entradas con `{coin, position, coinView}`.
Ambas en `dashboard/lib/view.ts`, con tests en `dashboard/lib/view.test.ts`.

## Fuera de alcance
- Rellenar huecos con candidatos del watchlist (se eligió grid adaptativo).
- Cambios en el bot/API/riesgo (es solo frontend).
- Reescribir la ruta `/sessions` (HISTORY) ni `/backtest` (siguen igual).
- Persistencia/estado nuevo; el modal es estado local de UI.

## Pruebas
- vitest para `slotLayout` y `slotItems` (lógica pura).
- Gate real: `npm run build` + `npm run lint` + `npx vitest run` verdes desde `dashboard/`.
- Sin jsdom: no se testea render; los componentes se validan por build + revisión visual del usuario.

## Criterios de aceptación
- La web LIVE ocupa toda la ventana sin scroll de página; con una sesión activa y posiciones abiertas,
  el centro muestra cada posición en su slot con gráfica + datos + decisiones del bot encima, y el
  reparto se adapta a 1/2/3-4 posiciones.
- El lanzamiento se hace desde un botón que abre un modal; con sesión activa, ese sitio muestra
  Close + Kill. Banda superior con Session P&L + gráfica + stats; raíl derecho con watchlist + tape.
- build + lint + vitest verdes. Sin tocar el bot.
