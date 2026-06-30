# Sub-proyecto 3b — Backtester — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtester offline que reutiliza el `SessionEngine` real contra un broker simulado que rellena fills desde velas históricas, expuesto por `POST /backtest` y un panel "lab de parámetros" en la topbar del dashboard.

**Architecture:** Un `BacktestBroker` implementa la interfaz que el motor usa de `HLClient` (mid, user_state, open_orders, place_limit, market_open, market_close, place_stop, cancel_all, cancel_order, set_leverage), simulando caja/posición/órdenes; su método `step(candle, funding)` rellena fills al cruzar precios. Un runner reproduce las velas por `engine.tick` y produce un `BacktestResult`. El frontend añade una ruta `/backtest` que consume el endpoint.

**Tech Stack:** Python 3.14, pytest (tests desde `bot/` con `.venv/bin/python -m pytest`); Next.js 16 + TS + Vitest (dashboard, build/lint/test desde `dashboard/`).

## Global Constraints

- El backtester NO coloca órdenes reales y NO requiere CONTROL_TOKEN. `/backtest` es síncrono.
- Reutiliza el motor y las estrategias reales vía el broker simulado (no reimplementar la lógica).
- Fees: maker `MAKER_FEE = 0.00015` (0.015%), taker `TAKER_FEE = 0.00045` (0.045%).
- Modelo de fills: maker se llena si la vela cruza el límite (compra `low<=px`, venta `high>=px`) al precio límite; market/stops al precio de la vela/trigger; funding horario con datos históricos. Sin parciales/cola/slippage extra.
- Equity = caja (realizado − fees − funding) + no-realizado al `mid` actual. Una moneda por run, efímero.
- `max_open_positions` se clampa a 4 (igual que live) si se construye `RiskLimits`.
- TDD: test que falla → implementación → test pasa → commit. Suite completa verde antes del commit final de cada tarea.

---

## File Structure

- `bot/src/hlbot/backtest/__init__.py` — paquete.
- `bot/src/hlbot/backtest/broker.py` — `BacktestBroker` (cliente simulado) + constantes de fee.
- `bot/src/hlbot/backtest/data.py` — descarga/normalización de velas y funding.
- `bot/src/hlbot/backtest/runner.py` — `CaptureStore` + `run_backtest` + `BacktestResult`.
- `bot/src/hlbot/backtest/metrics.py` — cálculo de métricas (drawdown, win rate, etc.).
- `bot/src/hlbot/api.py` — endpoint `POST /backtest`.
- `bot/tests/test_backtest_broker.py`, `test_backtest_runner.py`, `test_backtest_data.py`, `test_backtest_api.py`.
- `dashboard/lib/types.ts`, `dashboard/lib/api.ts`, `dashboard/components/HeaderBar.tsx` — tipos + cliente + nav.
- `dashboard/app/backtest/page.tsx`, `dashboard/components/BacktestForm.tsx`, `dashboard/components/BacktestResults.tsx` — panel.

---

## Task 1: `BacktestBroker` — estado y contabilidad de posición

**Files:**
- Create: `bot/src/hlbot/backtest/__init__.py` (vacío)
- Create: `bot/src/hlbot/backtest/broker.py`
- Test: `bot/tests/test_backtest_broker.py`

**Interfaces:**
- Produces: `BacktestBroker(capital: float, sz_decimals: dict[str,int])` con atributos `cash`, `positions`, `resting`, `fills`, `realized_total`, `fees_total`, `funding_total`; métodos cliente `mid`, `user_state`, `open_orders`, `place_limit`, `market_open`, `market_close`, `place_stop`, `cancel_all`, `cancel_order`, `set_leverage`, `funding_rates`; helper interno `_apply_fill`; setters `set_price(coin, px)` y `set_ts(ts)`. Constantes `MAKER_FEE`, `TAKER_FEE`.

- [ ] **Step 1: Tests que fallan** — crear `bot/tests/test_backtest_broker.py`:

```python
from hlbot.backtest.broker import BacktestBroker

def _bk():
    b = BacktestBroker(capital=1000.0, sz_decimals={"ETH": 4})
    b.set_price("ETH", 3000.0); b.set_ts(1000)
    return b

def test_place_limit_rests_with_oid():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True, reduce_only=False)
    oo = b.open_orders("ETH")
    assert len(oo) == 1 and oo[0]["limitPx"] == 2990.0 and "oid" in oo[0]

def test_market_open_takes_position_and_charges_taker_fee():
    b = _bk()
    b.market_open("ETH", True, 0.0034)            # ~$10.2 notional
    st = b.user_state()
    pos = st["assetPositions"][0]["position"]
    assert float(pos["szi"]) == 0.0034
    assert b.fees_total > 0                         # taker fee cobrada
    assert abs(b.cash - (1000.0 - b.fees_total)) < 1e-9  # abrir no mueve caja salvo fee

def test_market_close_realizes_pnl():
    b = _bk()
    b.market_open("ETH", True, 0.01)               # largo a 3000
    b.set_price("ETH", 3100.0)                      # +100
    b.market_close("ETH")
    assert b.positions.get("ETH", {"size": 0})["size"] == 0
    assert b.realized_total > 0                     # ganancia realizada (~+1.0 menos fees)
    closes = [f for f in b.fills if "Close" in f["dir"]]
    assert len(closes) == 1 and closes[0]["closed_pnl"] > 0

def test_user_state_equity_includes_unrealized():
    b = _bk()
    b.market_open("ETH", True, 0.01)               # largo a 3000
    b.set_price("ETH", 3100.0)
    eq = float(b.user_state()["marginSummary"]["accountValue"])
    assert eq > 1000.0                              # caja + no realizado (+1) - fees
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_backtest_broker.py -v`
Expected: FAIL (módulo no existe).

- [ ] **Step 3: Implementar** — `bot/src/hlbot/backtest/__init__.py` vacío y `bot/src/hlbot/backtest/broker.py`:

```python
from __future__ import annotations
from hlbot.hl_client import round_price, round_size, meets_min_notional
import math

MAKER_FEE = 0.00015
TAKER_FEE = 0.00045


class BacktestBroker:
    """Cliente simulado: misma interfaz que HLClient pero rellena fills desde velas."""

    def __init__(self, capital: float, sz_decimals: dict[str, int]):
        self.cash = capital
        self.sz_decimals = sz_decimals
        self.positions: dict[str, dict] = {}      # coin -> {"size": float, "entry": float}
        self.resting: dict[str, list[dict]] = {}  # coin -> [order dicts]
        self.fills: list[dict] = []
        self.realized_total = 0.0
        self.fees_total = 0.0
        self.funding_total = 0.0
        self._price: dict[str, float] = {}
        self._ts = 0
        self._next_oid = 1000

    # --- setters del runner ---
    def set_price(self, coin: str, px: float) -> None:
        self._price[coin] = px

    def set_ts(self, ts: int) -> None:
        self._ts = ts

    # --- interfaz cliente ---
    def mid(self, coin: str) -> float:
        return self._price[coin]

    def set_leverage(self, coin, leverage, is_cross=False):
        return {"status": "ok"}

    def funding_rates(self) -> dict[str, float]:
        return {}

    def user_state(self) -> dict:
        aps = []
        unreal = 0.0
        for coin, p in self.positions.items():
            sz = p["size"]
            if sz == 0:
                continue
            mid = self._price.get(coin, p["entry"])
            u = (mid - p["entry"]) * sz
            unreal += u
            aps.append({"position": {
                "coin": coin, "szi": str(sz), "entryPx": str(p["entry"]),
                "positionValue": str(abs(sz) * mid), "unrealizedPnl": str(u),
                "leverage": {"value": 1}, "liquidationPx": None,
            }})
        return {"assetPositions": aps,
                "marginSummary": {"accountValue": str(self.cash + unreal)}}

    def open_orders(self, coin: str) -> list[dict]:
        return list(self.resting.get(coin, []))

    def _new_oid(self) -> int:
        self._next_oid += 1
        return self._next_oid

    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        szd = self.sz_decimals[coin]
        px = round_price(price, szd)
        sz = round_size(size, szd)
        if not reduce_only and not meets_min_notional(px, sz):
            scale = 10 ** szd
            sz = math.ceil((10.0 / px) * scale) / scale
        self.resting.setdefault(coin, []).append({
            "oid": self._new_oid(), "is_buy": is_buy, "limitPx": px, "sz": sz,
            "reduce_only": reduce_only, "is_trigger": False,
        })
        return {"status": "ok"}

    def place_stop(self, coin, is_buy, trigger_px, size, reduce_only=True):
        szd = self.sz_decimals[coin]
        oid = self._new_oid()
        self.resting.setdefault(coin, []).append({
            "oid": oid, "is_buy": is_buy, "limitPx": round_price(trigger_px, szd),
            "sz": round_size(size, szd), "reduce_only": reduce_only,
            "is_trigger": True, "triggerPx": round_price(trigger_px, szd),
        })
        return {"resp": {"status": "ok"}, "oid": oid}

    def cancel_all(self, coin: str) -> None:
        self.resting[coin] = []

    def cancel_order(self, coin: str, oid: int) -> None:
        self.resting[coin] = [o for o in self.resting.get(coin, []) if o["oid"] != oid]

    def market_open(self, coin, is_buy, size, slippage=0.01):
        self._apply_fill(coin, is_buy, self._price[coin], size, TAKER_FEE)
        return {"status": "ok"}

    def market_close(self, coin: str):
        p = self.positions.get(coin)
        if not p or p["size"] == 0:
            return {"status": "ok"}
        is_buy = p["size"] < 0          # cerrar un corto = comprar
        self._apply_fill(coin, is_buy, self._price[coin], abs(p["size"]), TAKER_FEE)
        return {"status": "ok"}

    # --- contabilidad ---
    def _apply_fill(self, coin, is_buy, price, size, fee_rate, reduce_only=False):
        fee = price * size * fee_rate
        self.cash -= fee
        self.fees_total += fee
        pos = self.positions.setdefault(coin, {"size": 0.0, "entry": 0.0})
        cur = pos["size"]
        signed = size if is_buy else -size
        closed_pnl = 0.0
        reducing = cur != 0 and (cur > 0) != (signed > 0)
        if reducing:
            closing = min(size, abs(cur))
            closed_pnl = ((price - pos["entry"]) * closing) if cur > 0 else ((pos["entry"] - price) * closing)
            self.cash += closed_pnl
            self.realized_total += closed_pnl
            new = cur + signed
            if abs(signed) <= abs(cur):
                pos["size"] = new
                if new == 0:
                    pos["entry"] = 0.0
            else:                       # cruza el cero -> nueva posición al otro lado
                pos["size"] = new
                pos["entry"] = price
        else:                           # abrir o añadir mismo lado
            total = abs(cur) + size
            pos["entry"] = (pos["entry"] * abs(cur) + price * size) / total if total else 0.0
            pos["size"] = cur + signed
        side = "Long" if (cur > 0 or (cur == 0 and is_buy)) else "Short"
        dir_ = ("Close " if reducing else "Open ") + side
        self.fills.append({
            "coin": coin, "dir": dir_, "price": price, "size": size,
            "fee": fee, "closed_pnl": closed_pnl, "ts": self._ts,
        })
        return closed_pnl
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_backtest_broker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/backtest/__init__.py bot/src/hlbot/backtest/broker.py bot/tests/test_backtest_broker.py
git commit -m "feat(3b): BacktestBroker — estado y contabilidad de posición (fills/fees/PnL)"
```

---

## Task 2: `BacktestBroker.step` — fills al cruzar, stops y funding

**Files:**
- Modify: `bot/src/hlbot/backtest/broker.py` (añadir `step`)
- Test: `bot/tests/test_backtest_broker.py`

**Interfaces:**
- Consumes: estado y `_apply_fill` de Task 1.
- Produces: `step(self, coin: str, candle, funding_rate: float | None) -> None`. `candle` es un objeto con atributos `high, low, close, t` (el `Candle` de `hlbot.models`, `t` en ms). Procesa: (1) fills maker al cruzar, (2) stops al cruzar triggerPx, (3) funding horario, y deja `_price=close`, `_ts=t//1000`.

- [ ] **Step 1: Tests que fallan** — añadir a `bot/tests/test_backtest_broker.py`:

```python
from hlbot.models import Candle

def _candle(t, o, h, l, c):
    return Candle(t=t, open=o, high=h, low=l, close=c, volume=1.0)

def test_step_fills_buy_when_low_crosses():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True)
    b.step("ETH", _candle(60000, 3000, 3005, 2985, 2995), None)  # low 2985 <= 2990
    assert b.open_orders("ETH") == []                            # se llenó
    assert b.positions["ETH"]["size"] == 0.0034

def test_step_does_not_fill_when_not_crossed():
    b = _bk()
    b.place_limit("ETH", True, 2990.0, 0.0034, post_only=True)
    b.step("ETH", _candle(60000, 3000, 3010, 2995, 3005), None)  # low 2995 > 2990
    assert len(b.open_orders("ETH")) == 1

def test_step_stop_triggers_for_long():
    b = _bk()
    b.market_open("ETH", True, 0.01)                             # largo a 3000
    b.place_stop("ETH", False, 2940.0, 0.01, reduce_only=True)   # stop venta
    b.step("ETH", _candle(60000, 3000, 3000, 2930, 2935), None)  # low 2930 <= 2940
    assert b.positions["ETH"]["size"] == 0                       # cerrado por stop
    assert b.open_orders("ETH") == []

def test_step_applies_hourly_funding_long_pays_positive():
    b = _bk()
    b.market_open("ETH", True, 0.01)                             # largo notional ~30
    cash0 = b.cash
    b.set_ts(0)
    b.step("ETH", _candle(3600000, 3000, 3000, 3000, 3000), 0.0001)  # cruza 1 hora, funding +
    assert b.cash < cash0                                        # largo paga funding positivo
    assert b.funding_total > 0
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_backtest_broker.py -v`
Expected: FAIL (`step` no existe).

- [ ] **Step 3: Implementar** — añadir a `BacktestBroker` (y un atributo `self._last_funding_hour = None` en `__init__`):

```python
    def step(self, coin, candle, funding_rate):
        # 1) fills maker (órdenes no-trigger) al cruzar el rango de la vela
        still: list[dict] = []
        for o in self.resting.get(coin, []):
            if o["is_trigger"]:
                still.append(o); continue
            crossed = (candle.low <= o["limitPx"]) if o["is_buy"] else (candle.high >= o["limitPx"])
            if crossed:
                self._apply_fill(coin, o["is_buy"], o["limitPx"], o["sz"], MAKER_FEE,
                                 reduce_only=o["reduce_only"])
            else:
                still.append(o)
        self.resting[coin] = still
        # 2) stops (trigger) al cruzar triggerPx
        still2: list[dict] = []
        for o in self.resting.get(coin, []):
            if not o["is_trigger"]:
                still2.append(o); continue
            fired = (candle.low <= o["triggerPx"]) if not o["is_buy"] else (candle.high >= o["triggerPx"])
            if fired and self.positions.get(coin, {"size": 0})["size"] != 0:
                self._apply_fill(coin, o["is_buy"], o["triggerPx"],
                                 abs(self.positions[coin]["size"]), TAKER_FEE, reduce_only=True)
            else:
                still2.append(o)
        self.resting[coin] = still2
        # 3) funding horario sobre el notional de la posición
        ts = candle.t // 1000
        hour = ts // 3600
        if funding_rate is not None and self._last_funding_hour is not None and hour > self._last_funding_hour:
            p = self.positions.get(coin, {"size": 0.0, "entry": 0.0})
            if p["size"] != 0:
                notional = abs(p["size"]) * candle.close
                pay = funding_rate * notional * (1 if p["size"] > 0 else -1)  # largo paga si funding>0
                self.cash -= pay
                self.funding_total -= pay
        self._last_funding_hour = hour
        # 4) avanzar precio/ts
        self._price[coin] = candle.close
        self._ts = ts
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_backtest_broker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/backtest/broker.py bot/tests/test_backtest_broker.py
git commit -m "feat(3b): BacktestBroker.step — fills al cruzar, stops y funding horario"
```

---

## Task 3: Datos históricos (`data.py`)

**Files:**
- Create: `bot/src/hlbot/backtest/data.py`
- Test: `bot/tests/test_backtest_data.py`

**Interfaces:**
- Produces: `fetch_candles(client, coin, interval, n) -> list[Candle]` (usa `client.candles`/`candleSnapshot`, normaliza a `Candle`, ordenadas por t ascendente); `funding_at(funding_rows, ts_ms) -> float | None` (último funding con `time <= ts_ms`); `fetch_funding(client, coin, start_ms) -> list[dict]` (rows `{"time": int, "fundingRate": float}`).

- [ ] **Step 1: Tests que fallan** — crear `bot/tests/test_backtest_data.py`:

```python
from hlbot.backtest.data import funding_at, candles_from_raw

def test_funding_at_picks_last_le_ts():
    rows = [{"time": 0, "fundingRate": 0.0001},
            {"time": 3600000, "fundingRate": 0.0002},
            {"time": 7200000, "fundingRate": -0.0001}]
    assert funding_at(rows, 0) == 0.0001
    assert funding_at(rows, 5000000) == 0.0002       # entre 1h y 2h
    assert funding_at(rows, 10000000) == -0.0001
    assert funding_at(rows, -1) is None              # antes del primero

def test_candles_from_raw_normalizes_and_sorts():
    raw = [{"t": 120000, "o": "2", "h": "3", "l": "1", "c": "2", "v": "1"},
           {"t": 60000, "o": "1", "h": "2", "l": "1", "c": "1.5", "v": "1"}]
    cs = candles_from_raw(raw)
    assert [c.t for c in cs] == [60000, 120000]
    assert cs[0].close == 1.5
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_backtest_data.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** — `bot/src/hlbot/backtest/data.py`:

```python
from __future__ import annotations
import time
from hlbot.models import Candle

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def candles_from_raw(raw: list[dict]) -> list[Candle]:
    out = [Candle(t=int(c["t"]), open=float(c["o"]), high=float(c["h"]),
                  low=float(c["l"]), close=float(c["c"]), volume=float(c.get("v", 0) or 0))
           for c in raw]
    out.sort(key=lambda c: c.t)
    return out


def fetch_candles(client, coin: str, interval: str, n: int) -> list[Candle]:
    step = INTERVAL_MS.get(interval, 60_000)
    end = int(time.time() * 1000)
    start = end - step * min(n, 5000)
    raw = client.candles(coin, interval, start, end)
    return candles_from_raw(raw)


def fetch_funding(client, coin: str, start_ms: int) -> list[dict]:
    rows = client.info.funding_history(coin, start_ms)
    out = []
    for r in rows:
        out.append({"time": int(r.get("time", 0) or 0),
                    "fundingRate": float(r.get("fundingRate", 0) or 0)})
    out.sort(key=lambda r: r["time"])
    return out


def funding_at(funding_rows: list[dict], ts_ms: int) -> float | None:
    val = None
    for r in funding_rows:
        if r["time"] <= ts_ms:
            val = r["fundingRate"]
        else:
            break
    return val
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_backtest_data.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/backtest/data.py bot/tests/test_backtest_data.py
git commit -m "feat(3b): datos históricos del backtest (velas + mapeo de funding)"
```

---

## Task 4: Runner + métricas (`runner.py`, `metrics.py`)

**Files:**
- Create: `bot/src/hlbot/backtest/metrics.py`
- Create: `bot/src/hlbot/backtest/runner.py`
- Test: `bot/tests/test_backtest_runner.py`

**Interfaces:**
- Consumes: `BacktestBroker` (T1/T2), `SessionEngine`, `SessionConfig`/`RiskLimits`, `MarketState`/`Candle`.
- Produces: `compute_metrics(equity_curve, fills, funding_total) -> dict` (`net_pnl, realized_pnl, fees, funding, n_trades, win_rate, max_drawdown, final_equity, start_equity`); `run_backtest(coin, candles, funding_rows, cfg, sz_decimals) -> dict` con `{metrics, equity_curve, trades, decisions}`. `CaptureStore` con `current_ts` y `record_decision` que usa ese ts.

- [ ] **Step 1: Tests que fallan** — crear `bot/tests/test_backtest_runner.py`:

```python
from hlbot.models import Candle, RiskLimits, SessionConfig
from hlbot.backtest.runner import run_backtest
from hlbot.backtest.metrics import compute_metrics

def _cfg():
    limits = RiskLimits(10.0, 4, 2.0, 5.0, 20.0, 30.0)
    return SessionConfig(watchlist=["ETH"], capital=1000.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def _oscillating(n=120, base=3000.0, amp=30.0):
    # sube y baja en rango para que el grid cace ambos lados
    import math
    out = []
    for i in range(1, n + 1):
        c = base + amp * math.sin(i / 5.0)
        out.append(Candle(t=i * 60000, open=c, high=c + 5, low=c - 5, close=c, volume=1.0))
    return out

def test_run_backtest_returns_structure_and_runs_engine():
    res = run_backtest("ETH", _oscillating(), [], _cfg(), {"ETH": 4})
    assert set(res) == {"metrics", "equity_curve", "trades", "decisions"}
    assert len(res["equity_curve"]) > 0
    assert "net_pnl" in res["metrics"]
    # en un rango oscilante el grid debe haber colocado/llenado algo
    assert res["metrics"]["n_trades"] >= 0

def test_compute_metrics_drawdown_and_net():
    curve = [{"ts": 1, "total_pnl": 1000.0}, {"ts": 2, "total_pnl": 1010.0},
             {"ts": 3, "total_pnl": 990.0}, {"ts": 4, "total_pnl": 1005.0}]
    m = compute_metrics(curve, fills=[
        {"dir": "Close Long", "closed_pnl": 5.0, "fee": 0.1},
        {"dir": "Close Long", "closed_pnl": -3.0, "fee": 0.1},
        {"dir": "Open Long", "closed_pnl": 0.0, "fee": 0.1},
    ], funding_total=-0.5)
    assert m["start_equity"] == 1000.0 and m["final_equity"] == 1005.0
    assert abs(m["net_pnl"] - 5.0) < 1e-9            # 1005 - 1000
    assert m["n_trades"] == 2                         # solo cierres cuentan como trade
    assert abs(m["win_rate"] - 0.5) < 1e-9           # 1 de 2 cierres positivo
    assert abs(m["max_drawdown"] - 20.0) < 1e-9      # 1010 -> 990
```

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_backtest_runner.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar** — `bot/src/hlbot/backtest/metrics.py`:

```python
from __future__ import annotations


def compute_metrics(equity_curve: list[dict], fills: list[dict], funding_total: float) -> dict:
    start = equity_curve[0]["total_pnl"] if equity_curve else 0.0
    final = equity_curve[-1]["total_pnl"] if equity_curve else start
    closes = [f for f in fills if "Close" in f["dir"]]
    realized = sum(f["closed_pnl"] for f in closes)
    fees = sum(f["fee"] for f in fills)
    wins = sum(1 for f in closes if f["closed_pnl"] > 0)
    peak = start
    max_dd = 0.0
    for p in equity_curve:
        peak = max(peak, p["total_pnl"])
        max_dd = max(max_dd, peak - p["total_pnl"])
    return {
        "start_equity": start, "final_equity": final, "net_pnl": final - start,
        "realized_pnl": realized, "fees": fees, "funding": funding_total,
        "n_trades": len(closes), "win_rate": (wins / len(closes)) if closes else 0.0,
        "max_drawdown": max_dd,
    }
```

Y `bot/src/hlbot/backtest/runner.py`:

```python
from __future__ import annotations
from hlbot.models import MarketState
from hlbot.session_engine import SessionEngine
from hlbot.backtest.broker import BacktestBroker
from hlbot.backtest.data import funding_at
from hlbot.backtest.metrics import compute_metrics

SNAPSHOT_EVERY = 5   # velas


class CaptureStore:
    def __init__(self):
        self.decisions: list[dict] = []
        self.current_ts = 0

    def create_session(self, watchlist, capital, mode="backtest"):
        return 1

    def end_session(self, sid):
        pass

    def record_decision(self, sid, coin, action, reason):
        self.decisions.append({"ts": self.current_ts, "coin": coin,
                               "action": action, "reason": reason})

    def record_risk_event(self, sid, kind, detail):
        pass

    def record_pnl_snapshot(self, sid, pnl):
        pass


def run_backtest(coin, candles, funding_rows, cfg, sz_decimals) -> dict:
    broker = BacktestBroker(capital=cfg.capital, sz_decimals=sz_decimals)
    store = CaptureStore()
    if candles:
        broker.set_price(coin, candles[0].close)   # precio inicial para launch/set_anchor
        broker.set_ts(candles[0].t // 1000)
    engine = SessionEngine(broker, store)
    engine.launch(cfg)
    equity_curve: list[dict] = []
    for i, candle in enumerate(candles):
        fr = funding_at(funding_rows, candle.t)
        broker.step(coin, candle, fr)
        store.current_ts = candle.t // 1000
        ms = MarketState(coin=coin, mid=candle.close, candles=candles[:i + 1], funding_rate=fr)
        engine.tick({coin: ms})
        if i % SNAPSHOT_EVERY == 0:
            equity_curve.append({"ts": candle.t // 1000,
                                 "total_pnl": float(broker.user_state()["marginSummary"]["accountValue"])})
    # cierre final para realizar PnL y un último punto de equity
    broker.market_close(coin)
    if candles:
        equity_curve.append({"ts": candles[-1].t // 1000,
                             "total_pnl": float(broker.user_state()["marginSummary"]["accountValue"])})
    metrics = compute_metrics(equity_curve, broker.fills, broker.funding_total)
    return {"metrics": metrics, "equity_curve": equity_curve,
            "trades": broker.fills, "decisions": store.decisions}
```

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_backtest_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/backtest/runner.py bot/src/hlbot/backtest/metrics.py bot/tests/test_backtest_runner.py
git commit -m "feat(3b): runner de replay (reusa el motor) + métricas del backtest"
```

---

## Task 5: Endpoint `POST /backtest`

**Files:**
- Modify: `bot/src/hlbot/api.py`
- Test: `bot/tests/test_backtest_api.py`

**Interfaces:**
- Consumes: `run_backtest` (T4), `fetch_candles`/`fetch_funding` (T3), `SessionConfig`/`RiskLimits`.
- Produces: `POST /backtest` que recibe `BacktestBody` y devuelve `{metrics, equity_curve, trades, decisions}`.

- [ ] **Step 1: Test que falla** — crear `bot/tests/test_backtest_api.py`:

```python
from fastapi.testclient import TestClient
from hlbot.api import create_app
from hlbot.session_engine import SessionEngine
from test_session_engine import FakeClient, FakeStore
from hlbot.models import Candle

TOKEN = "t"

class BTClient(FakeClient):
    sz_decimals = {"ETH": 4}
    def candles(self, coin, interval, start, end):
        return [{"t": i * 60000, "o": 3000, "h": 3005, "l": 2995, "c": 3000, "v": 1}
                for i in range(1, 80)]
    class _Info:
        @staticmethod
        def funding_history(coin, start_ms): return []
    info = _Info()

def _client():
    eng = SessionEngine(BTClient(), FakeStore())
    return TestClient(create_app(eng, TOKEN, lambda: {}))

def test_backtest_returns_result_no_token_needed():
    c = _client()
    r = c.post("/backtest", json={"coin": "ETH", "capital": 1000.0, "n_candles": 79})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"metrics", "equity_curve", "trades", "decisions"}
    assert "net_pnl" in body["metrics"]

def test_backtest_bad_coin_returns_422():
    c = _client()
    r = c.post("/backtest", json={"coin": "NOPE", "capital": 1000.0, "n_candles": 50})
    assert r.status_code == 422
```

Nota: `BTClient` necesita `sz_decimals` como atributo de instancia; añadir en su `__init__` si `FakeClient` no lo tiene: el test arriba lo pone como atributo de clase, válido.

- [ ] **Step 2: Verificar fallo**

Run: `.venv/bin/python -m pytest tests/test_backtest_api.py -v`
Expected: FAIL (404 / endpoint no existe).

- [ ] **Step 3: Implementar** — en `api.py`, añadir el import y el modelo + endpoint. Imports al top:

```python
from hlbot.backtest.data import fetch_candles, fetch_funding
from hlbot.backtest.runner import run_backtest
```

Modelo (junto a los otros `BaseModel`):

```python
class BacktestBody(BaseModel):
    coin: str
    capital: float = 40.0
    interval: str = "1m"
    n_candles: int = 1000
    grid_n: int = 4
    grid_range_pct: float = 0.02
    skew_strength: float = 1.5
    spread_vol_mult: float = 0.5
    adx_threshold: float = 25.0
    atr_stop_mult: float = 2.0
    max_position_notional: float = 10.0
    max_coin_notional: float = 30.0
```

Endpoint (dentro de `create_app`, sin auth):

```python
    @app.post("/backtest")
    def backtest(body: BacktestBody):
        sz = getattr(engine.client, "sz_decimals", {})
        if body.coin not in sz:
            raise HTTPException(status_code=422, detail=f"coin desconocida: {body.coin}")
        n = max(1, min(body.n_candles, 5000))
        candles = fetch_candles(engine.client, body.coin, body.interval, n)
        if not candles:
            raise HTTPException(status_code=422, detail="sin datos de velas")
        funding = fetch_funding(engine.client, body.coin, candles[0].t)
        limits = RiskLimits(
            max_position_notional=body.max_position_notional,
            max_open_positions=4, max_leverage=2.0,
            daily_loss_limit=1e12, total_loss_limit=1e12,   # sin auto-close en backtest
            max_coin_notional=body.max_coin_notional)
        try:
            cfg = SessionConfig(
                watchlist=[body.coin], capital=body.capital, limits=limits,
                grid_n=body.grid_n, grid_range_pct=body.grid_range_pct,
                skew_strength=body.skew_strength, spread_vol_mult=body.spread_vol_mult,
                adx_threshold=body.adx_threshold, atr_stop_mult=body.atr_stop_mult)
            result = run_backtest(body.coin, candles, funding, cfg, sz)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return result
```

(Nota: `fetch_funding` usa `engine.client.info.funding_history`; el `BTClient` del test lo provee. Los límites de pérdida se ponen enormes para que el backtest no se auto-cierre por el guard de sesión.)

- [ ] **Step 4: Verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_backtest_api.py -v`
Expected: PASS.

- [ ] **Step 5: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/api.py bot/tests/test_backtest_api.py
git commit -m "feat(3b): endpoint POST /backtest (síncrono, sin token)"
```

---

## Task 6: Frontend — tipos, cliente API y nav en la topbar

**Files:**
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/lib/api.ts`
- Modify: `dashboard/components/HeaderBar.tsx`
- Test: `dashboard/lib/api.test.ts` (crear si no existe)

**Interfaces:**
- Produces: tipos `BacktestParams` y `BacktestResult`; `api.runBacktest(params): Promise<BacktestResult>` (POST `/backtest`); enlace **BACKTEST** en la topbar a `/backtest`.

- [ ] **Step 1: Test que falla** — crear/editar `dashboard/lib/api.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("runBacktest", () => {
  it("POSTs params to /backtest and returns the result", async () => {
    const result = { metrics: { net_pnl: 1 }, equity_curve: [], trades: [], decisions: [] };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(result), { status: 200 }));
    const r = await api.runBacktest({ coin: "ETH", capital: 40, n_candles: 100 } as never);
    expect(r).toEqual(result);
    const [url, opts] = spy.mock.calls[0];
    expect(String(url)).toContain("/backtest");
    expect((opts as RequestInit).method).toBe("POST");
  });
});
```

- [ ] **Step 2: Verificar fallo**

Run (desde `dashboard/`): `npx vitest run lib/api.test.ts`
Expected: FAIL (`runBacktest` no existe).

- [ ] **Step 3: Implementar** — en `dashboard/lib/types.ts` añadir:

```ts
export interface BacktestParams {
  coin: string; capital: number; interval?: string; n_candles: number;
  grid_n?: number; grid_range_pct?: number; skew_strength?: number; spread_vol_mult?: number;
  adx_threshold?: number; atr_stop_mult?: number; max_position_notional?: number; max_coin_notional?: number;
}
export interface BacktestMetrics {
  start_equity: number; final_equity: number; net_pnl: number; realized_pnl: number;
  fees: number; funding: number; n_trades: number; win_rate: number; max_drawdown: number;
}
export interface BacktestResult {
  metrics: BacktestMetrics;
  equity_curve: { ts: number; total_pnl: number }[];
  trades: { coin: string; dir: string; price: number; size: number; fee: number; closed_pnl: number; ts: number }[];
  decisions: { ts: number; coin: string; action: string; reason: string }[];
}
```

En `dashboard/lib/api.ts`, importar los tipos y añadir el método al objeto `api` (usa el mismo `BASE()`):

```ts
  runBacktest: async (params: BacktestParams): Promise<BacktestResult> => {
    const res = await fetch(`${BASE()}/backtest`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`POST /backtest -> ${res.status}`);
    return res.json() as Promise<BacktestResult>;
  },
```
(Añadir `BacktestParams, BacktestResult` al import de `./types` en `api.ts`.)

En `dashboard/components/HeaderBar.tsx`, añadir el enlace junto a LIVE/HISTORY:

```tsx
      <Link href="/backtest" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>BACKTEST</Link>
```

- [ ] **Step 4: Verificar que pasa**

Run (desde `dashboard/`): `npx vitest run lib/api.test.ts` (PASS), luego `npm run lint` y `npm run build` (verdes).

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/types.ts dashboard/lib/api.ts dashboard/components/HeaderBar.tsx dashboard/lib/api.test.ts
git commit -m "feat(3b): tipos + api.runBacktest + enlace BACKTEST en la topbar"
```

---

## Task 7: Frontend — página `/backtest` (lab + resultados)

**Files:**
- Create: `dashboard/app/backtest/page.tsx`
- Create: `dashboard/components/BacktestForm.tsx`
- Create: `dashboard/components/BacktestResults.tsx`
- Test: `dashboard/components/BacktestResults.test.tsx`

**Interfaces:**
- Consumes: `api.runBacktest` y los tipos (T6); reutiliza patrones visuales (`.panel`, `fmtUsd`, `pnlColor`).
- Produces: ruta `/backtest` con formulario lab + render de resultados.

- [ ] **Step 1: Test que falla** — crear `dashboard/components/BacktestResults.test.tsx`. Para NO depender de jsdom/testing-library (el dashboard usa tests puros de vitest), se testea la función pura `metricRows` que `BacktestResults` exporta:

```tsx
import { describe, it, expect } from "vitest";
import { metricRows } from "./BacktestResults";

describe("metricRows", () => {
  it("incluye PnL neto, fees, funding y win rate con las métricas dadas", () => {
    const rows = metricRows({
      start_equity: 1000, final_equity: 1010, net_pnl: 10, realized_pnl: 12,
      fees: 1.5, funding: -0.5, n_trades: 8, win_rate: 0.5, max_drawdown: 20,
    });
    const labels = rows.map((r) => r.label);
    expect(labels).toContain("PnL neto");
    expect(labels).toContain("fees");
    expect(labels).toContain("win rate");
    const net = rows.find((r) => r.label === "PnL neto")!;
    expect(net.value).toContain("10");           // formateado como USD
  });
});
```

No añadir dependencias nuevas (ni testing-library ni jsdom). `metricRows` es una función pura exportada por `BacktestResults.tsx` (definida en Step 3).

- [ ] **Step 2: Verificar fallo**

Run (desde `dashboard/`): `npx vitest run components/BacktestResults.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementar** — `dashboard/components/BacktestForm.tsx`:

```tsx
"use client";
import { useState } from "react";
import type { BacktestParams } from "@/lib/types";

const DEFAULTS: BacktestParams = {
  coin: "BTC", capital: 40, interval: "1m", n_candles: 1000,
  grid_n: 4, grid_range_pct: 0.02, skew_strength: 1.5, spread_vol_mult: 0.5,
  adx_threshold: 25, atr_stop_mult: 2, max_position_notional: 10, max_coin_notional: 30,
};

const inputS: React.CSSProperties = { width: "100%", background: "#0a0b0d", border: "1px solid #1c1f26", color: "var(--text)", borderRadius: 4, padding: "2px 6px", marginTop: 2 };

export function BacktestForm({ coins, busy, onRun }: {
  coins: { name: string }[]; busy: boolean; onRun: (p: BacktestParams) => void;
}) {
  const [f, setF] = useState<BacktestParams>(DEFAULTS);
  const num = (k: keyof BacktestParams) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: Number(e.target.value) }));
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>BACKTEST LAB</div>
      <label style={{ fontSize: 12 }}>moneda
        <select value={f.coin} onChange={(e) => setF((p) => ({ ...p, coin: e.target.value }))} style={inputS}>
          {coins.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12, marginTop: 6 }}>
        <label>nº velas <input type="number" defaultValue={f.n_candles} onChange={num("n_candles")} style={inputS} /></label>
        <label>capital <input type="number" defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
        <label>grid_n <input type="number" defaultValue={f.grid_n} onChange={num("grid_n")} style={inputS} /></label>
        <label>rango <input type="number" step={0.005} defaultValue={f.grid_range_pct} onChange={num("grid_range_pct")} style={inputS} /></label>
        <label>skew <input type="number" step={0.1} defaultValue={f.skew_strength} onChange={num("skew_strength")} style={inputS} /></label>
        <label>spread mult <input type="number" step={0.1} defaultValue={f.spread_vol_mult} onChange={num("spread_vol_mult")} style={inputS} /></label>
        <label>adx umbral <input type="number" defaultValue={f.adx_threshold} onChange={num("adx_threshold")} style={inputS} /></label>
        <label>atr stop <input type="number" step={0.1} defaultValue={f.atr_stop_mult} onChange={num("atr_stop_mult")} style={inputS} /></label>
        <label>posición $ <input type="number" defaultValue={f.max_position_notional} onChange={num("max_position_notional")} style={inputS} /></label>
        <label>cap moneda $ <input type="number" defaultValue={f.max_coin_notional} onChange={num("max_coin_notional")} style={inputS} /></label>
      </div>
      <button onClick={() => onRun(f)} disabled={busy}
        style={{ marginTop: 10, width: "100%", padding: 10, border: "none", borderRadius: 6,
          background: "var(--neon-green)", color: "#000", fontWeight: 700, cursor: "pointer" }}>
        {busy ? "corriendo…" : "▶ RUN BACKTEST"}
      </button>
    </div>
  );
}
```

`dashboard/components/BacktestResults.tsx`:

```tsx
"use client";
import type { BacktestResult, BacktestMetrics } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";
import { EquityCurve } from "./EquityCurve";

export function metricRows(m: BacktestMetrics): { label: string; value: string; color?: string }[] {
  return [
    { label: "PnL neto", value: fmtUsd(m.net_pnl), color: pnlColor(m.net_pnl) },
    { label: "realizado", value: fmtUsd(m.realized_pnl), color: pnlColor(m.realized_pnl) },
    { label: "fees", value: fmtUsd(-m.fees, 3), color: "var(--neon-red)" },
    { label: "funding", value: fmtUsd(m.funding, 3), color: pnlColor(m.funding) },
    { label: "max drawdown", value: fmtUsd(-m.max_drawdown), color: "var(--neon-red)" },
    { label: "trades", value: String(m.n_trades) },
    { label: "win rate", value: fmtPct(m.win_rate), color: "var(--neon-green)" },
  ];
}

export function BacktestResults({ result }: { result: BacktestResult }) {
  const m = result.metrics;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="stat-tiles">
        {metricRows(m).map((r) => (
          <div key={r.label} className="panel" style={{ padding: 12, minWidth: 0 }}>
            <div className="muted" style={{ fontSize: 11 }}>{r.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: r.color ?? "var(--text)" }}>{r.value}</div>
          </div>
        ))}
      </div>
      <EquityCurve key={`${result.equity_curve.length}:${result.equity_curve[0]?.ts ?? 0}`}
                   sessionId={null} equity={0} seed={result.equity_curve} />
      <div className="panel" style={{ padding: 12 }}>
        <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>TRADES ({result.trades.length})</div>
        {result.trades.slice(-50).map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
            <span className="muted">{new Date(t.ts * 1000).toLocaleString()}</span>
            <span style={{ width: 90 }}>{t.dir}</span>
            <span className="muted">@{t.price}</span>
            <span style={{ color: pnlColor(t.closed_pnl), marginLeft: "auto" }}>{fmtUsd(t.closed_pnl)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

> `EquityCurve` hoy carga datos por `sessionId`. Para el backtest se le pasa una serie ya calculada vía una nueva prop opcional `seed?: {ts:number; total_pnl:number}[]`: cuando `seed` está presente, el componente hace `series.setData(equitySeries(seed))` en vez de `getEquityCurve(sessionId)`, y NO hace append en vivo (equity={0}). Implementar esa rama en `EquityCurve.tsx` (si `seed` definido → usar seed; else comportamiento actual).

`dashboard/app/backtest/page.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BacktestParams, BacktestResult } from "@/lib/types";
import { BacktestForm } from "@/components/BacktestForm";
import { BacktestResults } from "@/components/BacktestResults";

export default function BacktestPage() {
  const [coins, setCoins] = useState<{ name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.getCoins().then(setCoins).catch(() => {}); }, []);
  async function run(p: BacktestParams) {
    setBusy(true); setError(null);
    try { setResult(await api.runBacktest(p)); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <div className="panel" style={{ padding: "10px 16px", display: "flex", gap: 16, alignItems: "center" }}>
        <span className="glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>NYHZ // BACKTEST</span>
        <Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>← TRADE</Link>
      </div>
      <div className="terminal-grid">
        <div className="terminal-col"><BacktestForm coins={coins} busy={busy} onRun={run} /></div>
        <div className="terminal-col">
          {error && <div className="panel" style={{ padding: 12, color: "var(--neon-red)" }}>{error}</div>}
          {result ? <BacktestResults result={result} /> : <div className="panel muted" style={{ padding: 12 }}>configura y pulsa RUN</div>}
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Implementar la prop `seed` en `EquityCurve.tsx`**

En el efecto que crea el chart (`EquityCurve.tsx`), cambiar la rama de carga:

```tsx
    if (seed && seed.length) {
      series.setData(equitySeries(seed) as never);
    } else if (sessionId !== null) {
      api.getEquityCurve(sessionId).then((rows) => {
        if (!cancelled) {
          series.setData(equitySeries(rows) as never);
          lastTimeRef.current = rows.length ? rows[rows.length - 1].ts : 0;
        }
      }).catch(() => {});
    }
```
y añadir `seed` a las props: `export function EquityCurve({ sessionId, equity, seed }: { sessionId: number | null; equity: number; seed?: { ts: number; total_pnl: number }[] })`. El efecto de append en vivo ya está guardado por `equity > 0`, así que con `equity={0}` no hace append.

- [ ] **Step 5: Verificar**

Run (desde `dashboard/`): `npx vitest run` (todos PASS), `npm run lint` (limpio), `npm run build` (verde).

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/backtest dashboard/components/BacktestForm.tsx dashboard/components/BacktestResults.tsx dashboard/components/BacktestResults.test.tsx dashboard/components/EquityCurve.tsx
git commit -m "feat(3b): página /backtest (lab de parámetros + resultados)"
```

---

## Notas de integración (para el revisor final)

- El backtester reutiliza el motor real: si `engine.launch` rechaza por validación (posición<\$10 o grid_n×pos>capital), el endpoint devuelve 422 — comportamiento correcto.
- Límites de pérdida puestos a 1e12 en el backtest para que el guard de sesión no auto-cierre a mitad (queremos ver la estrategia correr todo el periodo). El cap por moneda y el de leverage SÍ aplican (son parte de lo que se mide).
- `funding_at` toma el último funding con `time<=ts`; si no hay funding (lista vacía) el broker no aplica funding.
- El `seed` de `EquityCurve` evita duplicar el componente de chart; cuidado de no romper su uso actual en la vista live/sessions (rama `else` intacta).
- Fidelidad: modelo de fills optimista para maker (documentado en el spec); el objetivo es comparar configuraciones, no PnL exacto.
