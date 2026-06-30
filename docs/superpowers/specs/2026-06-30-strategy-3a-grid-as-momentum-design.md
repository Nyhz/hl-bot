# Sub-proyecto 3a — Grid (Avellaneda-Stoikov + funding) y Momentum mejorado

**Fecha:** 2026-06-30
**Estado:** diseño aprobado (pendiente de revisión del usuario antes del plan)

## Objetivo

Mejorar las dos ramas de la sesión actual (modo único "grid+momentum") sobre la base ya
endurecida (posición $10, guards de leverage/cap por moneda/4 posiciones, funding-aware):

1. **Grid** → reescritura estilo **Avellaneda-Stoikov**: precio de referencia que se
   re-centra con el inventario (arregla el ancla estática / reverse-DCA) + spread proporcional
   a la volatilidad, **más** sesgo por funding (el inventario neto tiende a cobrar funding).
2. **Momentum** → entrada más estricta, **trailing stop** y **salida por reversión** (recruce EMA).

NO cambia: tamaño de orden **$10** (cada rung / entrada), órdenes grid **maker (post-only)**,
todos los guards de riesgo, y el modelo de **un solo modo** con conmutación grid↔tendencia por
moneda según ADX. El objetivo sigue siendo aprender/observar, no rentabilidad.

**Fuera de alcance (es 3b):** modos de sesión seleccionables, launch con 2 tabs y campos por
modo, y la estrategia **funding carry** (delta-neutral spot+perp).

## Arquitectura y fontanería de datos

Las estrategias reciben `MarketState`. Hoy lleva `coin, mid, candles, funding_rate`. Se añade:

- **`inventory: float = 0.0`** — tamaño firmado de la posición abierta en esa moneda (`szi`,
  + largo / − corto). Lo **puebla el motor** cada tick desde `user_state` (ya lee posiciones);
  `main.py` lo deja en 0 por defecto.

La **volatilidad** se toma del **ATR ya calculado** (`atr(atr_period)`), en unidades de precio
absolutas (proxy de σ). No se añade indicador nuevo. El **funding** ya está en `MarketState`.

## Parte 1 — Grid Avellaneda-Stoikov + funding

Sustituye la lógica de `GridStrategy`. Por moneda, cada tick:

**Entradas:** `mid`, `sigma = atr(atr_period)`, `q_notional = inventory * mid` (notional firmado
de la posición), `f = funding_rate`, `cap = max_coin_notional`.

**Objetivo de inventario por funding (sesgo C):**
- `funding_tilt = 0.3` (default), `funding_min = 0.00005` (~0.005%/h).
- Si `|f| >= funding_min`: `phi_target = -sign(f) * funding_tilt`  (fracción de `cap`, en [-0.3, 0.3]).
  Funding positivo (largos pagan) ⇒ objetivo **corto** ⇒ el inventario neto cobra funding.
- Si no: `phi_target = 0` (neutral).

**Precio de referencia (re-centrado por inventario):**
- `phi = clamp(q_notional / cap, -1, 1)`  (fracción de inventario actual, firmada).
- `e = phi - phi_target`  (error de inventario respecto al objetivo).
- `reservation = mid - e * skew_strength * sigma`,  con `skew_strength = 1.5` (default).
  - Largo de más (`e>0`) ⇒ `reservation < mid` ⇒ ventas más agresivas, compras se retiran.

**Spread (proporcional a volatilidad):**
- `half_spread = max(min_spread_frac * mid, spread_vol_mult * sigma)`,
  con `min_spread_frac = 0.001` (0.1%) y `spread_vol_mult = 0.5` (default).
- `step = half_spread`  (separación entre rungs).

**Escalera (ladder) de órdenes:**
- `grid_n` rungs por lado (reutiliza el campo existente; default 4).
- Rung de compra `i` (i=1..grid_n): `reservation - i*step`. Rung de venta `i`: `reservation + i*step`.
- **Clamps:** descartar rungs que (a) crucen el mid (compra ≥ mid o venta ≤ mid → serían taker;
  ALO las rechazaría) o (b) se salgan de `±grid_range_pct` respecto al `reservation`
  (`grid_range_pct` pasa a ser el **clamp de rango máximo**, default 0.02).
- Tamaño de cada rung: `max_position_notional / price` (= $10), maker/post-only.

**Sin range-exit por precio.** Con re-centrado la referencia sigue al `mid`, así que un stop por
rango quedaría muerto. La protección del grid es: (1) el **cap de inventario** `max_coin_notional`
(bloquea el crecimiento de la posición), y (2) los **límites de pérdida de sesión** (daily/total →
auto-close de toda la sesión). `grid_range_pct` solo se usa como **clamp del rango de la escalera**
(no coloca rungs más allá de `±grid_range_pct` de la referencia).

**Reconciliación a la escalera deseada (cambio en el motor):** hoy el motor solo evita duplicar
rungs. Ahora, como el grid se re-centra, el motor:
1. calcula el conjunto de precios deseados (la escalera),
2. **cancela** las órdenes grid en reposo cuyo precio no esté a tolerancia `tol = step/2` de
   ningún precio deseado (cancelación selectiva por `oid`),
3. **coloca** los rungs deseados que no tengan ya una orden a `tol`.
   Como la tolerancia es media-step, si la `reservation` apenas se mueve la escalera deseada
   coincide con la existente y no hay churn; solo se reprice cuando se mueve de verdad.

## Parte 2 — Momentum mejorado

Sobre `TrendOverlayStrategy` y el motor:

**Entrada más estricta** (todas deben cumplirse para abrir):
- `ADX[-1] > adx_threshold` (como hoy),
- `ADX[-1] > ADX[-2]` (ADX creciente),
- `abs(EMA_fast - EMA_slow) / mid > ema_sep_frac`, con `ema_sep_frac = 0.001` (0.1%, default).

**Trailing stop (cambio en el motor):**
- Stop deseado largo = `mid - atr_stop_mult*ATR`; corto = `mid + atr_stop_mult*ATR`.
- El motor recuerda el stop actual por moneda (`stop_levels`) y su `oid`. Solo lo **mejora**:
  para un largo el trigger (venta) solo **sube**; para un corto solo **baja**. Cuando el stop
  deseado mejora al actual en más de `stop_trail_min = 0.1*ATR` (umbral para no recolocar en
  cada tick), **cancela el trigger viejo y coloca el nuevo**. Se añade `stop_trail_min` como
  parámetro derivado de ATR (no configurable).

**Salida por reversión:**
- Si hay posición de tendencia (`inventory != 0`) y las EMAs se recrutan en contra
  (largo y `EMA_fast < EMA_slow`, o corto y `EMA_fast > EMA_slow`) → emitir `CLOSE` (a mercado).

No cambia: una entrada por moneda, tamaño $10, stop como orden trigger real (ya verificada),
conmutación grid↔tendencia por ADX, cancelar grid al entrar en tendencia (#4 ya hecho).

## Cambios en el motor (resumen)

- Poblar `MarketState.inventory` cada tick (firmado, desde `user_state`).
- **Grid:** reconciliar a la escalera deseada (cancelar stale por `oid` + colocar faltantes).
- **Momentum:** mantener y **mejorar** el trailing stop (cancelar+recolocar trigger); ejecutar
  `CLOSE` por reversión (ya soportado).
- Nuevo en `HLClient`: `cancel_order(coin, oid)` (cancelación selectiva; hoy solo `cancel_all`).

## Parámetros (SessionConfig) y defaults

Nuevos campos en `SessionConfig` con default (NO se exponen en el form todavía; el rediseño del
launch es 3b). Los existentes se mantienen; `grid_range_pct` cambia de semántica a "clamp de rango
máximo del grid".

| Campo | Default | Significado |
|---|---|---|
| `skew_strength` | 1.5 | Multiplicador de σ para el desplazamiento de la referencia por inventario |
| `spread_vol_mult` | 0.5 | Half-spread = este × ATR (con suelo `min_spread_frac`) |
| `min_spread_frac` | 0.001 | Suelo del half-spread como fracción del precio |
| `funding_tilt` | 0.3 | Inclinación máx del objetivo de inventario por funding (fracción de cap) |
| `funding_min` | 0.00005 | Umbral de funding/h para activar el sesgo |
| `ema_sep_frac` | 0.001 | Separación mínima EMA_fast/EMA_slow para entrar en tendencia |
| `grid_range_pct` | 0.02 | (reinterpretado) clamp de rango máximo del grid respecto a la referencia |
| `grid_n` | 4 | Rungs por lado (sin cambio) |
| `atr_period`, `ema_fast`, `ema_slow`, `adx_period`, `adx_threshold`, `atr_stop_mult` | (actuales) | sin cambio |

## Pruebas (TDD)

Unitarias de estrategia:
- Grid: referencia = mid si neutral; referencia baja si largo, sube si corto; spread crece con σ;
  `phi_target` con signo opuesto al funding cuando `|f|>=funding_min`; rungs clampados a rango y
  sin cruzar el mid; tamaño de rung = $10.
- Momentum: entrada rechazada con EMAs pegadas o ADX no creciente; trailing stop monótono (solo
  mejora); `CLOSE` emitido al recruce de EMA estando en posición.

De motor (con `FakeClient`):
- Reconciliación: al moverse la referencia, cancela los rungs stale (por oid) y coloca los nuevos;
  si no se mueve, no hay churn.
- Trailing: el motor cancela+recoloca el trigger solo cuando el stop mejora; no toca si no mejora.
- `MarketState.inventory` poblado desde `user_state`.

Suite completa verde (bot pytest + dashboard build/lint/test si se toca algo del front —en 3a no
se toca el front).

## Criterios de aceptación

- El grid se re-centra visiblemente con el inventario y ensancha con volatilidad (observable en
  el dashboard vía las price-lines/triggers y las órdenes).
- El inventario neto tiende al lado que cobra funding cuando el funding supera el umbral.
- El momentum captura tendencias (trailing) y sale al revertir; entra menos en cruces débiles.
- Todos los guards y el tamaño $10 intactos. Sin tocar el launch.
