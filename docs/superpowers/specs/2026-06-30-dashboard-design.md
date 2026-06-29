# Diseño: Dashboard "MICRO-DEGEN TERMINAL" (sub-proyecto 2)

**Fecha:** 2026-06-30
**Estado:** Diseño aprobado (pendiente de revisión del usuario)
**Contexto:** El núcleo del bot + API + operacionalización están en `master` (bot Python con
FastAPI en `:3300`, runner launchd, plugin xbar). Este sub-proyecto construye el **dashboard
visual** —la prioridad del usuario— desde el que además se **lanzan y controlan las sesiones**.
Como Next.js es frontend puro (toda la lógica de Hyperliquid vive en Python), incluye una
**extensión de la API** del bot para servir los datos que hoy no expone.

## Objetivo y tono
Un **terminal de trading dark/neón, estilo "MICRO-DEGEN TERMINAL"**: monoespaciado, mucha
densidad de datos, gráficas por todas partes, micro-animaciones y estímulo "game-y". Centro de
mando: ves las **posiciones abiertas con protagonismo**, la **watchlist/candidatos con las
condiciones que faltan para abrir** (el "plan" del bot), y lanzas/cierras sesiones desde ahí.

## Decisiones tomadas (locked)

| Tema | Decisión |
|------|----------|
| Stack | Next.js + React + TypeScript; Lightweight-Charts; Framer Motion; sonner (+ sonido) |
| Layout | **Grid tiled** (command-center, todo a la vista, mínimo scroll) |
| Estética | Dark, monoespaciada, neón verde/rojo/ámbar, glow; badge modo TESTNET(naranja)/MAINNET(verde) |
| Tiempo real | **WebSocket enriquecido** (`:3300/ws`, ~1s) para lo vivo; REST para histórico/pesado |
| Control | Launch/Close/Kill desde el dashboard; token solo en servidor Next.js (proxy), nunca en el navegador |
| Frontend | Puro: consume solo la API del bot (REST + WS); NO toca Hyperliquid ni la BD directamente |
| Decomposición | 2a = extensión API de datos (Python) → 2b = dashboard Next.js |

## Arquitectura

```
Navegador (Next.js :3000)
  ├─ lecturas + WS  ─────────────▶ API del bot (:3300)  [CORS permite localhost:3000]
  └─ control (launch/close/kill) ─▶ rutas server Next.js ─(con X-Control-Token)─▶ API del bot
```

- **Lecturas y WebSocket**: el navegador conecta directo a `:3300` (la API habilita CORS para el
  origen del dashboard). Sin secretos.
- **Control**: el navegador llama a **rutas de servidor de Next.js** (API routes), que añaden el
  `X-Control-Token` (leído de `dashboard/.env.local`, server-side) y reenvían al bot. El token
  nunca llega al cliente.

---

# Sub-proyecto 2a — Extensión de la API de datos (Python)

Amplía `bot/src/hlbot/api.py` (y el runner/engine donde haga falta) para servir todo lo que el
terminal necesita. El **runner** cachea por tick los datos de cuenta (posiciones, PnL, fees,
funding) en una estructura compartida, para que la API responda sin pegar a Hyperliquid en cada
request del dashboard.

## 2a.1 Caché de cuenta en el runner
- En cada tick, además de construir `MarketState`, el runner consulta una vez `clearinghouseState`
  (posiciones, valor de cuenta) y, con menor frecuencia (p. ej. cada N ticks), `userFills` /
  `userFunding` / `userFees`. Guarda el resultado en un dict compartido `account_cache`.
- La API lee de `account_cache` (no de Hyperliquid directamente) → respuestas rápidas y sin
  rate-limit. Si la sesión está IDLE, el caché refleja el último estado conocido.

## 2a.2 Endpoints REST nuevos
- `GET /account` → `{equity, session_pnl, realized_pnl, unrealized_pnl, win_rate, fees_paid,
  funding, open_count, max_open}`.
- `GET /positions` → lista de `{coin, side, leverage, notional, size, entry_px, mark_px,
  unrealized_pnl, liq_px, opened_at}`.
- `GET /equity_curve?session_id=` → serie temporal de `pnl_snapshots` (para la curva).
- `GET /candles/{coin}?interval=1m` → velas recientes (de `market_candles` y/o el `MarketState`
  vivo) en el formato que consume Lightweight-Charts.
- `GET /tape?limit=` → fills + decisiones fusionados y ordenados por tiempo, cada uno con
  `{ts, kind (open|close|decision), coin, side, price, pnl?, reason}`.
- `GET /coins` → majors líquidos disponibles para el selector de launch (`{name, szDecimals}`),
  desde una lista curada validada contra `meta`.

## 2a.3 Snapshot enriquecido (`/state` y `/ws`)
El snapshot que devuelve `engine.snapshot()` se amplía con lo necesario para la sensación "viva":
- `account`: equity, session P&L, realizado/no realizado (de `account_cache`).
- `positions`: igual que `/positions` (resumen).
- por coin en `coins`: además de `mid/mode/triggers/conditions`, añadir el **valor actual y umbral
  de cada condición** (ya lo trae `Condition`) y un flag `armed` (todas las condiciones cumplidas).
- `tape_recent`: los últimos N eventos del tape.
- `session_started_at`, `mode` (testnet/mainnet), `paused`.

## 2a.4 CORS
- Habilitar CORS en la app FastAPI para el origen del dashboard (configurable; por defecto
  `http://localhost:3000`). Solo afecta a lecturas/WS; el control sigue por el proxy de Next.js.

## 2a.5 Tests
- Tests de cada endpoint nuevo con `TestClient` y un `engine`/`account_cache` fake (sin red),
  verificando forma de respuesta y, para `/account`/`/positions`, el mapeo desde el caché.
- Test de que las rutas de control siguen exigiendo token y las de lectura no.
- Test de la función pura que fusiona/ordena el tape y de la que formatea velas para el chart.

---

# Sub-proyecto 2b — Dashboard Next.js

## 2b.1 Estructura del proyecto
```
dashboard/
├── package.json, tsconfig.json, next.config.js, tailwind config
├── .env.local            # BOT_API_URL, CONTROL_TOKEN (server-side; en .gitignore)
├── app/                  # App Router
│   ├── layout.tsx, page.tsx (el terminal)
│   └── api/control/...    # rutas server proxy (launch/close/kill/limits) que inyectan el token
├── components/           # paneles (uno por responsabilidad, ver 2b.3)
├── lib/                  # cliente API (REST), hook de WebSocket, tipos, formato
└── styles/               # tema dark/neón, fuente monoespaciada
```

## 2b.2 Datos en el cliente
- **`useLiveSnapshot()`**: hook que abre el WebSocket a `:3300/ws`, mantiene el último snapshot y
  reconecta si se cae. Es la fuente del estado vivo (equity, P&L, posiciones, condiciones, tape).
- **Cliente REST** (`lib/api.ts`) para datos no-stream: `/equity_curve`, `/candles/{coin}`,
  `/tape` (histórico), `/coins`.
- **Control** vía `fetch('/api/control/...')` (rutas server de Next.js) → nunca expone el token.

## 2b.3 Paneles (componentes, una responsabilidad cada uno)
- **`HeaderBar`**: título, subtítulo, timer de sesión, `● LIVE`, badge de modo, botón Kill.
- **`EquityHero`**: EQUITY + SESSION P&L (number-tickers animados) + `EquityCurve` (área en vivo).
- **`StatTiles`**: OPEN x/y · WIN RATE · REALIZED · FEES PAID · FUNDING.
- **`OpenPositions`**: filas grandes con sparkline en vivo, entry→mark, PnL animado, liq, edad;
  clic enfoca el chart. Protagonista.
- **`FocusChart`**: Lightweight-Charts del par enfocado con overlays (rungs del grid, stop de
  tendencia, EMAs, entrada/liq) y los **triggers armados** como líneas etiquetadas; pulso al
  acercarse el precio.
- **`Watchlist`**: candidatos sin posición con mini-chart y **condiciones como gauges** (valor vs
  umbral) + niveles-gatillo; estado **ARMED** cuando todas se cumplen.
- **`Tape`**: feed en vivo de eventos con motivo, color-coded, autoscroll.
- **`LaunchPanel`**: formulario de lanzar sesión (watchlist de `/coins`, capital, límites, params);
  botones Close y Kill (con confirmación).
- **`Toaster`** (sonner) + sonido en abrir/cerrar posición.

## 2b.4 Animaciones / estímulo
- Number-tickers (count-up) en equity/PnL; glow/pulso en cambios de PnL y al "armarse" un trigger;
  `● LIVE` pulsante; flash de color en fills nuevos del tape; transición suave al cambiar de par
  enfocado. Todo coherente con el tono "degen terminal", sin penalizar el rendimiento.

## 2b.5 Verificación
- El dashboard se valida **manualmente contra el bot en testnet**: arrancar el bot (sesión en
  testnet), `npm run dev` en `dashboard/`, abrir `localhost:3000` y comprobar: equity/PnL en vivo,
  posiciones, watchlist con condiciones, chart con triggers, tape, y lanzar/cerrar/kill desde la UI.
- Lógica pura del frontend (formateadores, mapeo de snapshot→props, merge del tape) con tests
  unitarios donde aporte; el grueso visual se valida en navegador.

---

## Notas
- **Pre-mainnet (heredado):** sigue pendiente envolver el bucle del runner en `asyncio.to_thread`
  y verificar `place_stop` en testnet (no bloquean este sub-proyecto).
- **URL pública `tradingbot.lan`** (Caddy): cuando el dashboard esté, se puede exponer en la LAN;
  por ahora `localhost`. El plugin xbar ya enlaza a `:3300` y luego apuntará al dashboard.
- **Backtester** (sub-proyecto 3) sigue al final.
