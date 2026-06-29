# Diseño: Bot de trading en Hyperliquid + Dashboard

**Fecha:** 2026-06-29
**Estado:** Diseño aprobado (pendiente de revisión del usuario)

## 1. Resumen y objetivo

Un bot de trading **autónomo por sesiones** sobre perpetuos de Hyperliquid, con posiciones
pequeñas (~$10, el mínimo del exchange), financiado con ~30-40 $/mes. **El objetivo es
entretenimiento y aprendizaje, no rentabilidad.** El éxito se define como: corre sin reventar,
toma decisiones explicables, y es divertido y muy visual de observar.

Acompaña al bot un **dashboard extremadamente visual** que muestra en directo el "razonamiento"
del bot: gráficos en vivo con los niveles-gatillo dibujados ("si el precio cruza X, el bot hará
Y"), las condiciones de cada estrategia, posiciones, PnL, fees, funding e historial.

**Expectativa honesta de PnL:** aproximadamente cero menos fees. Se asume y se abraza como hobby.

## 2. Decisiones tomadas (locked)

| Tema | Decisión |
|------|----------|
| Lenguaje del bot | Python + `hyperliquid-python-sdk` oficial |
| Stack del dashboard | Next.js + React + TypeScript |
| Estrategia | Grid neutral maker-only + overlay de tendencia EMA(9/21)+ADX, tras interfaz `Strategy` pluggable |
| Conexión bot↔web | El bot persiste en SQLite y expone una API **FastAPI** (lectura + control) + **WebSocket**; Next.js es frontend puro |
| Modelo de operación | **Por sesiones** controladas desde el dashboard (no 24/7) |
| Selección de pares | Watchlist elegida por sesión de una **lista curada de majors líquidos** (BTC, ETH, SOL…) |
| Validación | **Testnet primero** (misma lógica, otra base_url), luego mainnet |
| Seguridad credenciales | **API/agent wallet** (solo firma, no custodia); key solo en `bot/`, fuera de git |
| Alertas | Toasts con **sonner** en el dashboard (abrir/cerrar posición) + sonido. Sin servicios externos |
| Despliegue | Mac Mini; proceso del bot vía **launchd** (auto-arranque + auto-reinicio) |
| Estructura | Monorepo `hl-bot/` con `bot/` (Python) y `dashboard/` (Next.js) |

## 3. Arquitectura general

```
hl-bot/
├── bot/          # Python: motor de sesiones, estrategias, backtester, FastAPI, SQLite
│   ├── .env      # API wallet key + master address (FUERA de git)
│   └── data.db   # SQLite
└── dashboard/    # Next.js + TS: frontend puro, consume la API del bot
```

Flujo de datos:

```
Hyperliquid API/WS ──▶ bot (motor) ──▶ SQLite
                            │
                            ▼
                     FastAPI (REST + WS) ──▶ Next.js (dashboard)
                            ▲
                            └── comandos de control (launch/close/kill/limits)
```

El dashboard nunca toca Hyperliquid ni la BD directamente: todo pasa por la API del bot.
Toda la lógica de Hyperliquid vive en un único lenguaje (Python).

## 4. Hechos técnicos de Hyperliquid (referencia para implementación)

Verificado contra la documentación oficial (`hyperliquid.gitbook.io`) y el SDK Python en 2026.

**Redes / testnet**
- Mainnet: `https://api.hyperliquid.xyz` · Testnet: `https://api.hyperliquid-testnet.xyz`.
- Faucet testnet: `https://app.hyperliquid-testnet.xyz/drip` (1.000 USDC mock; históricamente
  exige haber depositado en mainnet con la misma address).
- El SDK cambia de red solo por `base_url` (`constants.MAINNET_API_URL` / `TESTNET_API_URL`)
  pasado a `Info(base_url=...)` y `Exchange(base_url=...)`.

**Autenticación**
- No hay "API key/secret/token" tradicional. Auth = **firma EIP-712 con private key de Ethereum**.
- Práctica: **API wallet (agent wallet)** aprobada vía `ApproveAgent`; solo firma, no custodia
  fondos. En el SDK: `secret_key` = key de la API wallet, `account_address` = address **master**.
- Las queries de lectura usan la address master y **son públicas y sin auth**. → El dashboard
  no necesita ninguna credencial.

**Restricciones de trading**
- Mínimo de orden: **$10 de notional** (excepción: órdenes reduce-only que cierran posición).
- `szDecimals` por activo define precisión de tamaño. Precios: máx 5 cifras significativas y
  máx `6 - szDecimals` decimales (perps).
- Fees perps Tier 0 (donde viviremos): **taker 0.045%, maker 0.015%** sobre notional.
- ⚠️ **Builder codes:** pueden añadir hasta 10 bps/lado (0.20% ida/vuelta), letal a $10. El bot
  debe operar **sin builder fee**.
- **Funding horario**: pago = `tamaño × precio_oráculo × tasa`; típico ±0.01%/h, tope 4%/h.

**Datos / endpoints**
- Velas: `candleSnapshot` (intervalos 1m…1M), **máx 5.000 velas por petición**. → Grabamos
  nuestros propios datos desde el día 1 para backtests profundos.
- Cuenta: `clearinghouseState` (posiciones/margen/valor), `userFills`/`userFillsByTime`,
  `userFees`, `userFunding`, `fundingHistory`, `portfolio` (serie de PnL), `openOrders`.
- WebSocket: `l2Book`, `bbo`, `trades`, `candle`, `allMids`, `userFills`, `userFundings`,
  `orderUpdates`, `clearinghouseState`, etc. (≤10 conexiones, ≤1.000 suscripciones por IP).
- Órdenes: límite (`Alo`=post-only / `Ioc` / `Gtc`), market, trigger (`tp`/`sl`), TWAP,
  `reduceOnly`, `cloid`.
- Rate limit REST: 1.200 de peso/min por IP.
- Pares líquidos recomendados para tamaño pequeño: **BTC, ETH, SOL** (libros profundos).

**Backtesting de histórico profundo (más allá de 5.000 velas):** grabación propia continua
desde el día 1 (tabla `market_candles`); opcionalmente el archivo S3 `hyperliquid-archive`
(LZ4, *requester-pays*, subido ~mensualmente) para L2/contextos.

## 5. Decomposición en sub-proyectos

El sistema es grande para un solo spec. Se divide en **3 sub-proyectos**, cada uno con su propio
ciclo spec → plan → implementación, en este orden:

1. **Núcleo del bot + API** (este spec lo detalla) — SDK, motor de sesiones, estrategias, SQLite
   y FastAPI+WS. Validado en testnet.
2. **Backtester** — corre las estrategias sobre histórico modelando fees + funding horario; usado
   para afinar parámetros antes de mainnet.
3. **Dashboard** — frontend Next.js con todas las vistas visuales.

Dependencias: dashboard → API → núcleo; el backtester reusa la interfaz `Strategy` del núcleo.

---

# Sub-proyecto 1 — Núcleo del bot + API (spec detallado)

## 1.1 Componentes

- **`hl_client`** — envoltorio del SDK oficial. Conmuta testnet/mainnet por config. Métodos de
  lectura (posiciones, fills, fees, funding, velas, contextos) y de escritura (colocar/cancelar
  órdenes, market/limit/trigger). Garantiza ausencia de builder fee.
- **`session_engine`** — máquina de estados de sesión (ver 1.2). Orquesta el bucle de evaluación,
  aplica límites de seguridad, y delega decisiones a las estrategias.
- **`strategy`** — interfaz común + implementaciones `GridStrategy` y `TrendOverlayStrategy`.
- **`risk`** — evaluación de límites (pérdida diaria/total, exposición, leverage, nº posiciones).
- **`store`** — capa de persistencia SQLite (esquema en 1.5).
- **`api`** — servicio FastAPI (REST + WebSocket) que expone lectura y control (1.6).

Cada componente tiene una responsabilidad única e interfaz definida, testeable de forma aislada.

## 1.2 Máquina de estados de sesión

```
IDLE ──Launch──▶ SCANNING ──▶ ACTIVE ──Close──▶ CLOSING ──▶ IDLE
                                 └──────Kill (con confirmación)──────▶ FLAT ──▶ IDLE
```

- **Launch**: recibe config (watchlist, capital, límites, params de estrategia). Pasa a SCANNING.
- **SCANNING**: evalúa los pares de la watchlist; cuando una estrategia da señal, despliega y pasa
  a ACTIVE (sigue escaneando los demás).
- **ACTIVE**: gestiona posiciones/órdenes; cada tick evalúa límites **antes** de actuar.
- **Close**: deja de abrir nuevas; las posiciones abiertas llegan a término natural (sus
  stops/targets/rungs). Cuando todo cierra → IDLE.
- **Kill** (con confirmación explícita en la API): cierra todo a mercado de inmediato → FLAT → IDLE.
- Si se cruza un límite de riesgo: la sesión se pausa automáticamente (no abre nuevas) y lo registra.

El motor es un proceso de larga duración (junto con la API) siempre encendido; **el trading solo
ocurre dentro de una sesión activa**.

## 1.3 Interfaz de estrategia

```python
class Strategy(Protocol):
    def evaluate(self, market_state: MarketState) -> list[Decision]: ...
    def armed_triggers(self, market_state: MarketState) -> list[Trigger]: ...
    def conditions(self, market_state: MarketState) -> list[Condition]: ...
```

- `Decision`: acción a ejecutar (abrir/cerrar/ajustar orden) con su motivo (para el log).
- `Trigger`: `{nivel_precio, lado, acción, descripción}` — los niveles que el dashboard dibuja
  ("si el precio cruza X → Y"). En grid son los rungs; en tendencia, niveles de entrada/stop/cross.
- `Condition`: `{nombre, valor_actual, umbral, cumplida?}` — el estado en vivo de las condiciones,
  para visualizar qué falta para que el bot actúe.

**GridStrategy** (maker-only): ladder de órdenes límite `Alo` en un rango; spacing ≥ ~0.3% (por
encima del hurdle de fees maker 0.03%); stop de rango duro. Cada rung es un trigger.

**TrendOverlayStrategy** (EMA 9/21 + ADX(14)): cuando ADX>umbral y EMAs alineadas, pausa el grid
de ese par y monta la tendencia con trailing stop basado en ATR. Publica EMAs, umbral y niveles.

## 1.4 Riesgo / límites (configurables por sesión)

- Kill-switch global (con confirmación) → cierra todo a mercado.
- Límite de pérdida **diaria** y **total** → pausa la sesión al cruzarse.
- Exposición: tamaño máximo por posición, nº máximo de posiciones abiertas.
- Leverage máximo por par y por sesión.
- Todos verificados en cada tick **antes** de cualquier acción de apertura.

## 1.5 Esquema SQLite

Tablas: `sessions`, `orders`, `fills`, `positions`, `decisions` (el razonamiento: qué disparó
cada acción), `pnl_snapshots`, `funding_payments`, `fees`, `market_candles` (grabación propia
continua para backtests profundos), `risk_events` (límites alcanzados, pausas, kills).

## 1.6 Superficie de la API

**Lectura (REST):** estado del motor/sesión, posiciones, PnL, fees, funding (cobrado/pagado),
historial de sesiones y trades, triggers armados por par, condiciones en vivo, log de decisiones.

**Control (REST, protegido con token local simple):**
- `POST /session/launch` (watchlist, capital, límites, params)
- `POST /session/close`
- `POST /session/kill` (requiere flag de confirmación)
- `POST /limits` (actualizar límites)

**WebSocket:** empuja en vivo precios, fills, cambios de triggers/condiciones, decisiones y PnL.

## 1.7 Testnet y despliegue

- Toda la lógica corre primero en **testnet** (faucet 1.000 USDC mock) cambiando solo `base_url`.
- El proceso bot+API se gestiona en el Mac Mini con **launchd** (arranque al boot, auto-reinicio,
  logs a fichero). El dashboard (sub-proyecto 3) se sirve aparte.

## 1.8 Estrategia de testing

- Tests unitarios de cada estrategia con `MarketState` sintéticos (señales, triggers, condiciones).
- Tests del motor de sesión sobre la máquina de estados (transiciones, límites, kill/close).
- Tests del `store` (persistencia round-trip).
- Tests de integración del `hl_client` contra **testnet**.
- Verificación de que ninguna orden lleva builder fee y que se respeta el mínimo de $10 / precisión.

---

# Sub-proyecto 2 — Backtester (esbozo)

Corre las estrategias (misma interfaz `Strategy`) sobre velas históricas (grabadas + paginadas
vía `candleSnapshot`), **modelando fees maker + funding horario + supuesto de ejecución maker**.
Validación walk-forward (optimizar en una ventana, testear en la siguiente). Se usa para afinar
parámetros antes de pasar a mainnet. Spec propio cuando llegue su turno.

# Sub-proyecto 3 — Dashboard (esbozo)

Next.js + React + TS. Lightweight-Charts para gráficos financieros en vivo, Framer Motion para
animaciones, sonner para toasts (+ sonido) al abrir/cerrar posición. Vistas:

- **Live session**: gráfico(s) por par con triggers dibujados (líneas/zonas animadas) y panel de
  condiciones en tiempo real.
- **Posiciones & PnL**: abiertas con entrada/stop/target, PnL realizado/no-realizado en vivo.
- **Costes**: fees y funding (cobrado/pagado), acumulado y por posición.
- **Historial**: sesiones y trades pasados con su decisión asociada.
- **Controles**: Launch / Close / Kill (con confirmación) y configuración de límites.
- **Backtests**: lanzar y visualizar resultados.

Consume exclusivamente la API del bot (REST + WebSocket). Spec propio cuando llegue su turno.
