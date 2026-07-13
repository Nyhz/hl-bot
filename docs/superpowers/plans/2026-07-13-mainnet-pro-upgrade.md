# Plan: upgrade "pro" del bot para mainnet (microestructura + modos nuevos)

Fecha: 2026-07-13. Origen: revisión con gorrito de trader experto contrastada con
literatura de market making (A-S + microprice + OFI + toxicity gate), docs de HL
(fees, WS, rate limits) y ecosistema de bots. Decisión del usuario: integrar TODO,
por fases iterables.

**Diagnóstico central:** el grid A-S es sólido pero cotiza contra un mid REST de
hasta 5s de antigüedad → selección adversa estructural. Fees maker (0.015% base,
~3bps round-trip) cubiertos por min_spread_frac=10bps; el coste real es la
toxicidad de los fills, hoy ni medida.

**Restricción de diseño transversal:** el backtester alimenta MarketState solo con
velas. Todos los campos de microestructura son Optional y las estrategias DEGRADAN
a mid/ATR cuando faltan → el backtest sigue midiendo el mismo código sin WS.

**Rate limits (por qué el tick sigue a 5s hasta F3):** open_orders REST pesa 20;
4 monedas × 12 ticks/min × 20 = 960/min de 1200. Acelerar el loop exige primero
rastrear órdenes localmente vía WS orderUpdates (F3). El presupuesto por DIRECCIÓN
(10k acciones + 1/USDC negociado) se mide en F3 con contador propio.

## Fases

### F1 — Datos en vivo por WebSocket (cimiento) ✅ cuando: suite verde + verificado en testnet
- `hlbot/marketdata.py`: wrapper de `WebsocketManager` (SDK). Suscripciones `bbo` +
  `trades` para LIQUID_MAJORS fijas (sin subs dinámicas). Thread-safe.
- Por moneda: best bid/ask con tamaños, **microprice** = (bid·ask_sz + ask·bid_sz)/(bid_sz+ask_sz),
  **vol realizada** (EWMA de r²/dt sobre mids de bbo, expuesta como sigma_px por
  horizonte), **flujo firmado del tape** (deque rodante; flow_ratio = firmado/total).
- El SDK NO reconecta: `ensure_alive()` desde el runner — si todo lleva >30s stale,
  reconstruir el manager (throttled).
- `MarketState` gana Optional: best_bid/ask, bid_sz/ask_sz, microprice, sigma_px,
  flow_ratio, flow_usd, ws_age. `build_market_state` los puebla si frescos (≤3s).
- El mid del tick sale del bbo WS si fresco (REST all_mids como fallback).
- Snapshot `/state.coins[c]` expone microprice/sigma/flow/bbo (para dashboard F3.5).

### F2 — Grid A-S v2 (el upgrade de estrategia)
- Fair value: `(1-w)·mid + w·microprice` (w=microprice_weight, default 0.3).
- Reserva: `fair - e·k·σ + ofi_weight·flow_ratio·σ` (flujo comprador sube la reserva).
- σ: sigma_px realizada del WS; fallback ATR (idéntico a hoy) si None.
- Toxicity gate: |flow_ratio| ventana corta > umbral → el engine cancela reposo del
  grid (guard: no tocar coins con posición de tendencia) y no cotiza durante
  cooldown. Decisiones con reason visible en el tape.
- Params nuevos en SessionConfig (defaults conservadores): microprice_weight=0.3,
  ofi_weight=0.5, flow_window_s=15, toxicity_flow_ratio=0.7, toxicity_min_usd=densidad
  mínima para señal, toxicity_cooldown_s=30.
- Test de paridad: sin campos micro (backtest) el grid v2 = grid v1.

### F3 — Ejecución pro: batch, contador de acciones, markouts
- Reconciliador → `bulk_place_limits`/`cancel_orders` (1 request IP-wise por batch).
- Contador de acciones L1 en HLClient (gastadas por tipo) → `/state.l1_actions`;
  base del tile del dashboard.
- **Markouts**: ring buffer de mids (180s, muestreo ≥0.5s) en marketdata; job por
  tick calcula bps firmados a favor del fill a +5s/+30s/+120s → columnas en fills
  (migración) + endpoint `GET /markouts`. Fills fuera de la ventana del ring quedan
  NULL (sin inventar datos).
- Funding cacheado 60s (metaAndAssetCtxs pesa 20; cambiaba poco y se pedía por tick).

### F3b — Rastreo local de órdenes + tick 1s (SEPARADA de F3 a propósito)
- WS `orderUpdates` → estado local de órdenes (seed por REST + updates), resync
  periódico; solo entonces bajar TICK_SECONDS a 1s (hoy open_orders REST pesa 20
  por moneda y tick: a 1s reventaría el límite de 1200/min).
- El estado local de órdenes tiene carreras sutiles (orden colocada entre seed y
  subscribe): merece fase propia con verificación larga en testnet.

### F3.5 — Dashboard: microestructura visible
- Panel de markouts (curva bps vs horizonte — EL número de un MM).
- Tile de presupuesto de acciones (gastado/ganado, proyección de agotamiento).
- Gauges por moneda: spread bbo, flow_ratio, estado toxicity (quoting/pulled).

### F4 — Modo 2: funding carry delta-neutral (spot+perp intra-HL)
- Solo mainnet (spot de testnet es de pega — ya documentado). Fees spot 0.04/0.07 base.
- HLClient: spot meta, órdenes spot, balances. Sesión con `mode=carry`: comprar spot X
  + corto perp X (maker ambas patas), cobrar funding horario; salir si funding medio
  N horas < umbral o por límites de sesión. Realismo: APR de un dígito en majors;
  el valor es el modo visual/educativo (curva de funding acumulado).
- Launch con selector de modo en el dashboard (2 tabs, ya diseñado en 2026-06).

### F5 — Riesgo de cartera
- Cap de **delta neto agregado** en $ (majors correlacionan >0.8: 4 longs de $10 = 1
  long de $40): nuevo límite en RiskLimits + check en _risk_ok (reducir siempre pasa).
- Vol-sizing: notional del rung = clamp(k/σ_frac, $10, max_position_notional) — solo
  muerde si el usuario sube el cap por posición (mínimo $10 de HL es el suelo).

### F6 — Los divertidos (identidad del proyecto)
- **Shadow whale**: subs WS `userFills` de N direcciones objetivo (dato público);
  tape de la whale en el dashboard; modo espejo opcional (replica a escala $10,
  entrada maker, caps de riesgo propios).
- **Consciencia de liquidaciones**: detectar cascada (ráfaga de volumen agresivo +
  desplazamiento) → retirada defensiva (extiende toxicity gate); tras cascada,
  ventana de re-entrada del grid (mean reversion post-barrido).

## Orden y protocolo
F1 → F2 → F3 → F3.5 → F5 → F4 → F6 (F5 antes que F4 por ser barato; F4 requiere
mainnet para verificar la pata spot). Cada fase: TDD, suite completa verde,
verificación en vivo en testnet (skill `verify` del repo), commit propio, push.

## Fuentes clave
- Fees/tiers/rebates: hyperliquid-docs/trading/fees (maker 0.015% base → rebate -0.003% top).
- WS subscriptions: hyperliquid-docs/for-developers/api/websocket/subscriptions.
- Rate limits: 1200 weight/min IP; dirección 10k + 1/USDC; batch = 1 req IP-wise;
  cancels con colchón min(limit+100k, 2×limit).
- A-S práctico: microprice + OFI + toxicity gate como extensiones estándar
  (quantlabsnet, crypto-chassis, hummingbot avellaneda).
