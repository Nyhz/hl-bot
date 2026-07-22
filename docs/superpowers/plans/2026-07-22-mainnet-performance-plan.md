# Plan de optimización de performance en mainnet (post-canario s10)

Fecha: 2026-07-22 · Base: ~10h de sesión 10 (primer canario mainnet, capital 60/6).

## Diagnóstico (con datos de s10)

| Hallazgo | Dato | Consecuencia |
|---|---|---|
| Fill rate 2.5% (30 fills / 1.182 places) vs 27% en testnet s8 | decisions/fills s10 | La cola es real: cada recolocación pierde antigüedad |
| 72% del churn = toxicity gate en ciclo (303/419 cancels) | reasons de decisions | Pull → cooldown 30s → recolocar → pull… en horas activas |
| Umbral $400k < flujo MEDIO de la tarde (BTC $689k/15s, pico $15.6M; mañana $112k) | micro_snapshots | El umbral absoluto en USD no puede funcionar: flujo intradía varía ~6× |
| Los pulls SÍ coinciden con las horas de peor markout (16-17h: -4.1/-8.5 bps) | fills+decisions por hora | El gate protege; el problema es el ciclo de recolocación, no la idea |
| Repricing propio (reconcile stale) solo 119 cancels | reasons | La tolerancia 0.75·half NO es la palanca principal |
| Vol mainnet ≈ ½ de la semana de soak 3 (BTC 2.15 vs 3.67 bps/tick) | micro_snapshots | Menos cruces de rungs → menos fills; NO recalibrar el suelo con 1 día |
| Fees 1.44 bps maker, 30/30 maker; WS 2 reconexiones/10h; funding capturado (fix fkey) | fills, risk_events | Ejecución e infra sanas: el coste está en cola y gate |

## Fases

### F0 — Telemetría (código puro; deploy con restart+rehidratación)
- **T1 cruces fantasma**: contar cuando el mid cruza el nivel de un rung en reposo
  sin fill → % de fills perdidos por cola. Columna/evento ligero + query.
- **T2 eficacia del gate**: por cada disparo, snapshot de flow/ratio; durante el
  cooldown, contar cruces de niveles retirados y estimar su markout con el ring
  de mids → "fills evitados" y si eran buenos o malos. Responde con datos si el
  gate ahorra más de lo que cuesta en cola.

### F1 — Toxicity gate v2 (palanca nº1; datos ya suficientes)
- **Umbral relativo**: marketdata mantiene EWMA de flow_total por coin (τ ~30 min);
  tóxico si `|ratio| ≥ 0.85` **y** `flow ≥ 3×EWMA` **y** `flow ≥ $100k` (suelo anti-madrugada).
- **Histéresis (Schmitt)**: disparo a 0.85, re-arme solo cuando `|ratio| < 0.5` —
  evita el parpadeo.
- **Cooldown escalonado**: 30→60→120→180s si re-dispara; reset tras 10 min tranquilos.
  Mata el ciclo pull/replace en tendencias sostenidas.
- Aplicación: campos nuevos de SessionConfig → **requiere sesión nueva** (kill+relaunch
  autorizados por el usuario). Objetivo: pulls/h en horas activas ÷5, places/fill < 20.

### F2 — Preservación de cola (repricing)
- Edad mínima de orden antes de reprice (~90 s) salvo drift > 1.5·half — las órdenes
  viejas son las que se llenan. Medir con T1 antes/después. Secundaria (119 cancels),
  pero barata.

### F3 — Estructural (F3b del plan pro): orderUpdates por WS
- Fills y estado de órdenes en ~1 s sin REST (open_orders pesa 20/coin/tick);
  re-quote más rápido tras fill. Hacer cuando F1/F2 estén estables y medidas.

### F4 — Calibración con ≥1 semana de mainnet (NO antes)
- Suelo min_spread_frac 15 bps vs distribución real de vol y fill rate.
- Lado comprador de ETH (cuadrante débil del soak 3: m120 +1.6 vs +7.6).
- Funding tilt: ya medible (fix fkey); ETH funding ≈ 0 desde 16:00 → verificar que
  el sesgo short de ETH se relaja como manda el diseño.
- Subir caps (coin/Δneto) solo tras semanas verdes — es la palanca de PnL identificada.

## Reglas
- Cada fase: tests + métrica antes/después. Nada se recalibra con < 1 semana de datos
  salvo evidencia estructural (como el gate).
- Cambios de **código** → deploy con restart+rehidratación (sesión sobrevive).
  Cambios de **config de sesión** → solo con kill+relaunch autorizados por el usuario.
- KPIs de la semana: fill rate > 8%, places/fill < 20, markout 30s medio ≥ +2 bps,
  fees/gross < 30%, 0 taker, pulls/h activos ÷5 vs s10.
