# Dashboard 2a — Extensión de la API de datos: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ampliar la API del bot (FastAPI en `:3300`) para servir todo lo que el dashboard "MICRO-DEGEN TERMINAL" necesita: cuenta/equity/PnL, posiciones, curva de equity, velas, tape y coins disponibles; con un snapshot enriquecido por WebSocket y CORS para el frontend.

**Architecture:** Funciones puras nuevas en `bot/src/hlbot/account.py` (derivan cuenta/posiciones/tape/velas desde respuestas crudas de Hyperliquid y el store) — testeables sin red. El runner (`main.py`) cachea por tick los datos de cuenta en un dict compartido `account_cache`; la API lee de ese caché (no pega a Hyperliquid por request). Nuevos endpoints REST + snapshot enriquecido en `/state` y `/ws` + CORS. La lógica de Hyperliquid sigue 100% en Python; el frontend (2b) solo consumirá esta API.

**Tech Stack:** Python 3.11+, FastAPI + Starlette CORS middleware, `hyperliquid-python-sdk`, `sqlite3`, `pytest` + `httpx` (TestClient).

## Global Constraints

- Frontend puro: el dashboard consume SOLO esta API (REST + WS). La API es la única que habla con Hyperliquid o la BD.
- La API lee de `account_cache` (poblado por el runner), NO de Hyperliquid en cada request (evita rate-limit).
- Endpoints de control (launch/close/kill/limits) SIGUEN exigiendo `X-Control-Token`; los de lectura (`/account`, `/positions`, `/equity_curve`, `/candles`, `/tape`, `/coins`, `/state`, `/history`) y el `/ws` NO llevan token.
- CORS habilitado para el origen del dashboard (por defecto `http://localhost:3000`), configurable por env `DASHBOARD_ORIGIN`.
- Funciones de cara al frontend devuelven JSON; importes monetarios como `float`.
- `create_app` debe seguir siendo retrocompatible: la firma nueva añade un parámetro con default, para que el runner y los tests existentes no rompan.
- Velas para Lightweight-Charts: cada vela `{time, open, high, low, close}` con `time` en SEGUNDOS (epoch), ascendente.

**Estructura de ficheros (2a):**

```
bot/src/hlbot/account.py        # NUEVO: funciones puras (posiciones, cuenta, tape, velas)
bot/src/hlbot/store.py          # + get_pnl_snapshots, get_candles
bot/src/hlbot/hl_client.py      # + user_fills, user_funding (lectura)
bot/src/hlbot/main.py           # + account_cache + refresh + account_provider en create_app
bot/src/hlbot/api.py            # + endpoints REST, CORS, snapshot enriquecido
bot/src/hlbot/session_engine.py # snapshot(): + 'armed' por coin y 'mode'
bot/tests/test_store.py         # + tests de los read helpers
bot/tests/test_account.py       # NUEVO: tests de las funciones puras
bot/tests/test_api.py           # + tests de endpoints nuevos y snapshot enriquecido
```

---

### Task 1: Store — read helpers para curva de equity y velas

**Files:**
- Modify: `bot/src/hlbot/store.py`
- Test: `bot/tests/test_store.py`

**Interfaces:**
- Consumes: tablas `pnl_snapshots`, `market_candles` (ya existen).
- Produces: `Store.get_pnl_snapshots(session_id: int) -> list[dict]` (filas `{ts, total_pnl}` orden ascendente); `Store.get_candles(coin: str, interval: str, limit: int = 500) -> list[dict]` (filas `{t, open, high, low, close, volume}` orden ascendente por `t`).

- [ ] **Step 1: Escribir el test que falla** (añadir a `bot/tests/test_store.py`)

```python
def test_get_pnl_snapshots(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_pnl_snapshot(sid, -0.10)
    store.record_pnl_snapshot(sid, 0.25)
    rows = store.get_pnl_snapshots(sid)
    assert [r["total_pnl"] for r in rows] == [-0.10, 0.25]
    assert "ts" in rows[0]

def test_get_candles(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    with store._conn() as conn:
        for t in (3, 1, 2):  # desordenados a propósito
            conn.execute(
                "INSERT OR REPLACE INTO market_candles "
                "(coin, interval, t, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("ETH", "1m", t, 10.0, 11.0, 9.0, 10.5, 1.0))
    rows = store.get_candles("ETH", "1m", limit=10)
    assert [r["t"] for r in rows] == [1, 2, 3]  # ascendente
    assert rows[0]["close"] == 10.5
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py::test_get_pnl_snapshots tests/test_store.py::test_get_candles -v`
Expected: FAIL (`AttributeError: 'Store' object has no attribute 'get_pnl_snapshots'`)

- [ ] **Step 3: Implementar** (añadir métodos a la clase `Store` en `store.py`)

```python
    def get_pnl_snapshots(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT ts, total_pnl FROM pnl_snapshots WHERE session_id=? ORDER BY id",
                (session_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_candles(self, coin: str, interval: str, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT t, open, high, low, close, volume FROM market_candles "
                "WHERE coin=? AND interval=? ORDER BY t DESC LIMIT ?",
                (coin, interval, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]  # ascendente por t
```

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/store.py bot/tests/test_store.py
git commit -m "feat(api): Store get_pnl_snapshots + get_candles"
```

---

### Task 2: `account.py` — funciones puras (posiciones, cuenta, tape, velas)

**Files:**
- Create: `bot/src/hlbot/account.py`
- Test: `bot/tests/test_account.py`

**Interfaces:**
- Consumes: nada (puras).
- Produces:
  - `summarize_positions(clearinghouse_state: dict) -> list[dict]` → `[{coin, side, leverage, notional, size, entry_px, mark_px, unrealized_pnl, liq_px}]`.
  - `compose_account(clearinghouse_state: dict, fills: list[dict], funding_total: float, session_start_value: float, max_open: int) -> dict` → `{equity, session_pnl, realized_pnl, unrealized_pnl, win_rate, fees_paid, funding, open_count, max_open, positions}`.
  - `merge_tape(decisions: list[dict], fills: list[dict], limit: int = 50) -> list[dict]` → eventos `{ts, kind, coin, side, price, pnl, reason}` orden descendente por `ts`.
  - `format_candles(raw: list[dict]) -> list[dict]` → `[{time, open, high, low, close}]` con `time` en segundos, ascendente.

- [ ] **Step 1: Escribir los tests que fallan** (`bot/tests/test_account.py`)

```python
from hlbot.account import summarize_positions, compose_account, merge_tape, format_candles

CH = {
    "marginSummary": {"accountValue": "49.16"},
    "assetPositions": [
        {"position": {"coin": "BTC", "szi": "0.0002", "entryPx": "67000",
                      "positionValue": "12.40", "unrealizedPnl": "0.07",
                      "leverage": {"value": 3}, "liquidationPx": "47200.9"}},
        {"position": {"coin": "ETH", "szi": "-0.003", "entryPx": "3121",
                      "positionValue": "10.10", "unrealizedPnl": "-0.27",
                      "leverage": {"value": 2}, "liquidationPx": "4525.9"}},
    ],
}
FILLS = [
    {"coin": "BTC", "time": 1000, "dir": "Close Long", "px": "67550",
     "closedPnl": "0.02", "fee": "0.0015"},
    {"coin": "SOL", "time": 900, "dir": "Close Short", "px": "150",
     "closedPnl": "-0.17", "fee": "0.0009"},
]

def test_summarize_positions_side_and_fields():
    pos = summarize_positions(CH)
    assert len(pos) == 2
    btc = next(p for p in pos if p["coin"] == "BTC")
    assert btc["side"] == "long" and btc["leverage"] == 3
    eth = next(p for p in pos if p["coin"] == "ETH")
    assert eth["side"] == "short"
    assert btc["unrealized_pnl"] == 0.07 and btc["notional"] == 12.40

def test_compose_account():
    acc = compose_account(CH, FILLS, funding_total=0.002,
                          session_start_value=50.0, max_open=4)
    assert acc["equity"] == 49.16
    assert abs(acc["session_pnl"] - (49.16 - 50.0)) < 1e-9
    assert abs(acc["realized_pnl"] - (0.02 - 0.17)) < 1e-9     # suma closedPnl
    assert abs(acc["fees_paid"] - (0.0015 + 0.0009)) < 1e-9
    assert acc["funding"] == 0.002
    assert acc["open_count"] == 2 and acc["max_open"] == 4
    # win rate: 1 ganador (0.02) de 2 cierres = 0.5
    assert abs(acc["win_rate"] - 0.5) < 1e-9
    assert abs(acc["unrealized_pnl"] - (0.07 - 0.27)) < 1e-9
    assert len(acc["positions"]) == 2

def test_merge_tape_orders_desc_and_classifies():
    decisions = [{"ts": 950, "coin": "BTC", "action": "place_limit", "reason": "grid rung"}]
    tape = merge_tape(decisions, FILLS, limit=10)
    assert [e["ts"] for e in tape] == [1000, 950, 900]  # desc
    close = next(e for e in tape if e["ts"] == 1000)
    assert close["kind"] == "close" and close["coin"] == "BTC" and close["pnl"] == 0.02
    dec = next(e for e in tape if e["ts"] == 950)
    assert dec["kind"] == "decision" and dec["reason"] == "grid rung"

def test_format_candles_to_seconds_ascending():
    raw = [{"t": 60000, "o": "10", "h": "12", "l": "9", "c": "11", "v": "1"},
           {"t": 120000, "o": "11", "h": "13", "l": "10", "c": "12", "v": "1"}]
    out = format_candles(raw)
    assert out[0] == {"time": 60, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}
    assert out[1]["time"] == 120
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_account.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.account'`)

- [ ] **Step 3: Implementar `account.py`**

```python
from __future__ import annotations


def summarize_positions(clearinghouse_state: dict) -> list[dict]:
    out: list[dict] = []
    for ap in clearinghouse_state.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        liq = p.get("liquidationPx")
        out.append({
            "coin": p.get("coin"),
            "side": "long" if szi > 0 else "short",
            "leverage": (p.get("leverage", {}) or {}).get("value"),
            "notional": float(p.get("positionValue", 0) or 0),
            "size": abs(szi),
            "entry_px": float(p.get("entryPx", 0) or 0),
            "mark_px": None,  # el frontend usa el mid vivo del snapshot/ws
            "unrealized_pnl": float(p.get("unrealizedPnl", 0) or 0),
            "liq_px": float(liq) if liq not in (None, "") else None,
        })
    return out


def compose_account(clearinghouse_state: dict, fills: list[dict], funding_total: float,
                    session_start_value: float, max_open: int) -> dict:
    positions = summarize_positions(clearinghouse_state)
    equity = float(clearinghouse_state.get("marginSummary", {}).get("accountValue", 0) or 0)
    unrealized = sum(p["unrealized_pnl"] for p in positions)
    closes = [f for f in fills if "Close" in (f.get("dir") or "")]
    realized = sum(float(f.get("closedPnl", 0) or 0) for f in closes)
    fees_paid = sum(float(f.get("fee", 0) or 0) for f in fills)
    wins = sum(1 for f in closes if float(f.get("closedPnl", 0) or 0) > 0)
    win_rate = (wins / len(closes)) if closes else 0.0
    return {
        "equity": equity,
        "session_pnl": equity - session_start_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "win_rate": win_rate,
        "fees_paid": fees_paid,
        "funding": funding_total,
        "open_count": len(positions),
        "max_open": max_open,
        "positions": positions,
    }


def merge_tape(decisions: list[dict], fills: list[dict], limit: int = 50) -> list[dict]:
    events: list[dict] = []
    for d in decisions:
        events.append({
            "ts": int(d.get("ts", 0)),
            "kind": "decision",
            "coin": d.get("coin"),
            "side": None,
            "price": None,
            "pnl": None,
            "reason": d.get("reason", ""),
        })
    for f in fills:
        dir_ = f.get("dir") or ""
        events.append({
            "ts": int(f.get("time", 0)),
            "kind": "close" if "Close" in dir_ else "open",
            "coin": f.get("coin"),
            "side": "short" if "Short" in dir_ else ("long" if "Long" in dir_ else None),
            "price": float(f.get("px", 0) or 0),
            "pnl": float(f.get("closedPnl", 0) or 0) if "Close" in dir_ else None,
            "reason": dir_,
        })
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]


def format_candles(raw: list[dict]) -> list[dict]:
    out = [{
        "time": int(c["t"]) // 1000,
        "open": float(c["o"]), "high": float(c["h"]),
        "low": float(c["l"]), "close": float(c["c"]),
    } for c in raw]
    out.sort(key=lambda c: c["time"])
    return out
```

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_account.py -v`
Expected: PASS (4)

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/account.py bot/tests/test_account.py
git commit -m "feat(api): account.py (posiciones, cuenta, tape, velas) puras"
```

---

### Task 3: HLClient — lectura de fills y funding

**Files:**
- Modify: `bot/src/hlbot/hl_client.py`
- Test: `bot/tests/test_hl_client_testnet.py`

**Interfaces:**
- Consumes: `self.info`, `self.address`.
- Produces: `HLClient.user_fills() -> list[dict]`; `HLClient.user_funding(start_ms: int) -> list[dict]`.

> Igual que el resto de métodos de `HLClient`, se validan en testnet (integración, se saltan sin credenciales). Confirma en testnet los nombres del SDK (`info.user_fills`, `info.user_funding`) y ajusta si difieren, manteniendo la firma pública.

- [ ] **Step 1: Implementar los métodos** (añadir a la clase `HLClient`, tras `place_stop`)

```python
    def user_fills(self) -> list[dict]:
        return self.info.user_fills(self.address)

    def user_funding(self, start_ms: int) -> list[dict]:
        return self.info.user_funding(self.address, start_ms)
```

- [ ] **Step 2: Extender el test de integración** (añadir a `bot/tests/test_hl_client_testnet.py`, dentro del bloque `skipif`)

```python
def test_user_fills_and_funding_return_lists():
    from hlbot.config import Config
    from hlbot.hl_client import HLClient
    client = HLClient(Config.from_env())
    assert isinstance(client.user_fills(), list)
    assert isinstance(client.user_funding(0), list)
```

- [ ] **Step 3: Ejecutar suite (integración se salta sin credenciales)**

Run: `cd bot && .venv/bin/python -m pytest -q`
Expected: verde; integración SKIPPED.

- [ ] **Step 4: Commit**

```bash
git add bot/src/hlbot/hl_client.py bot/tests/test_hl_client_testnet.py
git commit -m "feat(api): HLClient user_fills + user_funding (lectura)"
```

---

### Task 4: Runner — `account_cache` y `account_provider`

**Files:**
- Modify: `bot/src/hlbot/main.py`
- Test: `bot/tests/test_runner.py`

**Interfaces:**
- Consumes: `account.compose_account`, `client.user_state/user_fills/user_funding`, `engine.session_start_value`, `engine.cfg.limits.max_open_positions`.
- Produces: `refresh_account_cache(client, engine, cache: dict, fetch_extras: bool) -> None` (rellena `cache` in-place con el dict de `compose_account` + guarda `_fills` para el tape); el runner crea `account_cache: dict` y se lo pasa a `create_app(..., account_provider=lambda: account_cache)`.

- [ ] **Step 1: Escribir el test que falla** (añadir a `bot/tests/test_runner.py`)

```python
from hlbot.main import refresh_account_cache

class _AcctClient:
    def user_state(self):
        return {"marginSummary": {"accountValue": "49.16"},
                "assetPositions": [{"position": {"coin": "BTC", "szi": "0.0002",
                    "entryPx": "67000", "positionValue": "12.4", "unrealizedPnl": "0.07",
                    "leverage": {"value": 3}, "liquidationPx": "47200"}}]}
    def user_fills(self):
        return [{"coin": "BTC", "time": 1, "dir": "Close Long", "px": "67550",
                 "closedPnl": "0.02", "fee": "0.0015"}]
    def user_funding(self, start_ms):
        return [{"delta": {"usdc": "0.001"}}, {"delta": {"usdc": "-0.0005"}}]

class _Eng:
    session_start_value = 50.0
    class cfg:
        class limits:
            max_open_positions = 4

def test_refresh_account_cache_populates():
    cache = {}
    refresh_account_cache(_AcctClient(), _Eng(), cache, fetch_extras=True)
    assert cache["equity"] == 49.16
    assert cache["open_count"] == 1
    assert abs(cache["funding"] - (0.001 - 0.0005)) < 1e-9
    assert cache["_fills"][0]["coin"] == "BTC"
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py::test_refresh_account_cache_populates -v`
Expected: FAIL (`ImportError: cannot import name 'refresh_account_cache'`)

- [ ] **Step 3: Implementar en `main.py`**

Añade el import y la constante junto a los demás:
```python
from hlbot.account import compose_account

ACCOUNT_EXTRAS_EVERY = 6   # cada cuántos ticks refrescar fills/funding (más pesados)
```

Añade la función (in-place sobre `cache`; conserva `_fills`/`_funding` entre llamadas si no se refrescan):
```python
def refresh_account_cache(client, engine, cache: dict, fetch_extras: bool) -> None:
    try:
        ch = client.user_state()
    except Exception as e:
        print(f"[account_cache] user_state error: {e}", flush=True)
        return
    if fetch_extras:
        try:
            cache["_fills"] = client.user_fills()
            funding = client.user_funding(0)
            cache["_funding"] = sum(float(f.get("delta", {}).get("usdc", 0) or 0) for f in funding)
        except Exception as e:
            print(f"[account_cache] extras error: {e}", flush=True)
    fills = cache.get("_fills", [])
    funding_total = cache.get("_funding", 0.0)
    max_open = engine.cfg.limits.max_open_positions if engine.cfg else 0
    acc = compose_account(ch, fills, funding_total, engine.session_start_value, max_open)
    acc["_fills"] = fills
    acc["_funding"] = funding_total
    cache.clear()
    cache.update(acc)
```

En `_trade_loop`, dentro del `try` y tras `engine.tick(states)` (o siempre que haya sesión), refresca el caché:
```python
            refresh_account_cache(client, engine, account_cache,
                                  fetch_extras=(ticks % ACCOUNT_EXTRAS_EVERY == 0))
```
(Necesitarás pasar `account_cache` a `_trade_loop`; añádelo a su firma y al `create_task`.)

En `main()`, crea el caché y pásalo al provider:
```python
    account_cache: dict = {}
    app = create_app(engine, cfg.control_token, lambda: shared, lambda: account_cache)
    ...
        asyncio.create_task(_trade_loop(engine, client, store, shared, account_cache))
```
Y actualiza la firma de `_trade_loop(engine, client, store, shared, account_cache)`.

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py -v`
Expected: PASS (incluye el nuevo)

- [ ] **Step 5: Smoke import + suite + commit**

```bash
cd bot && .venv/bin/python -c "import hlbot.main; print('ok')"
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/main.py bot/tests/test_runner.py
git commit -m "feat(api): account_cache en el runner + account_provider"
```

---

### Task 5: API — endpoints REST nuevos + CORS

**Files:**
- Modify: `bot/src/hlbot/api.py`
- Test: `bot/tests/test_api.py`

**Interfaces:**
- Consumes: `account.merge_tape`, `account.format_candles`; `engine.store.get_pnl_snapshots/get_candles/get_decisions`; `engine.client.sz_decimals`; `account_provider()`.
- Produces: `create_app(engine, control_token, market_state_provider, account_provider=lambda: {})`; nuevos GET `/account`, `/positions`, `/equity_curve`, `/candles/{coin}`, `/tape`, `/coins`; CORS middleware.

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_api.py`)

```python
from hlbot.store import Store

def _client_with_data(tmp_path):
    from hlbot.api import create_app
    from hlbot.session_engine import SessionEngine
    from test_session_engine import FakeClient, FakeStore  # FakeClient tiene sz_decimals? ver nota
    # store real con datos sembrados
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_pnl_snapshot(sid, -0.1); store.record_pnl_snapshot(sid, 0.2)
    store.record_decision(sid, "ETH", "place_limit", "grid rung")
    with store._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO market_candles "
                     "(coin, interval, t, open, high, low, close, volume) "
                     "VALUES ('ETH','1m',60000,10,12,9,11,1)")
    client = FakeClient()
    client.sz_decimals = {"BTC": 5, "ETH": 4, "SOL": 2}
    engine = SessionEngine(client, store)
    engine.session_id = sid
    acct = {"equity": 49.16, "session_pnl": -0.84, "open_count": 1, "max_open": 4,
            "positions": [{"coin": "ETH", "side": "long", "unrealized_pnl": -0.2}],
            "_fills": [{"coin": "ETH", "time": 70000, "dir": "Close Long",
                        "px": "11", "closedPnl": "0.02", "fee": "0.001"}]}
    app = create_app(engine, TOKEN, lambda: {}, lambda: acct)
    return TestClient(app), sid

def test_account_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/account")
    assert r.status_code == 200 and r.json()["equity"] == 49.16

def test_positions_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/positions")
    assert r.status_code == 200 and r.json()[0]["coin"] == "ETH"

def test_equity_curve_endpoint(tmp_path):
    client, sid = _client_with_data(tmp_path)
    r = client.get(f"/equity_curve?session_id={sid}")
    assert [p["total_pnl"] for p in r.json()] == [-0.1, 0.2]

def test_candles_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/candles/ETH")
    assert r.json()[0] == {"time": 60, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0}

def test_tape_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/tape")
    kinds = {e["kind"] for e in r.json()}
    assert "close" in kinds and "decision" in kinds

def test_coins_endpoint(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/coins")
    names = [c["name"] for c in r.json()]
    assert "BTC" in names and "ETH" in names and "SOL" in names
```

> Nota: `FakeClient` (en `test_session_engine.py`) no define `sz_decimals` por defecto; el test se lo asigna explícitamente (`client.sz_decimals = {...}`). No modifiques `FakeClient`.

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_api.py -k "endpoint" -v`
Expected: FAIL (404 / `create_app() takes 3 positional args` hasta implementar)

- [ ] **Step 3: Implementar en `api.py`**

Imports nuevos arriba:
```python
from fastapi.middleware.cors import CORSMiddleware
import os
from hlbot.account import merge_tape, format_candles

LIQUID_MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
```

Cambia la firma y añade CORS + endpoints dentro de `create_app`:
```python
def create_app(engine: SessionEngine, control_token: str,
               market_state_provider, account_provider=lambda: {}) -> FastAPI:
    app = FastAPI(title="hlbot")
    origin = os.getenv("DASHBOARD_ORIGIN", "http://localhost:3000")
    app.add_middleware(
        CORSMiddleware, allow_origins=[origin], allow_methods=["*"],
        allow_headers=["*"],
    )
    # ... (_auth y endpoints existentes se mantienen) ...

    @app.get("/account")
    def account():
        a = dict(account_provider())
        a.pop("_fills", None); a.pop("_funding", None)
        return a

    @app.get("/positions")
    def positions():
        return account_provider().get("positions", [])

    @app.get("/equity_curve")
    def equity_curve(session_id: int):
        return engine.store.get_pnl_snapshots(session_id)

    @app.get("/candles/{coin}")
    def candles(coin: str, interval: str = "1m", limit: int = 500):
        raw = engine.store.get_candles(coin, interval, limit)
        # get_candles devuelve {t (ms), open, high, low, close, volume};
        # format_candles espera {t (ms), o, h, l, c} y divide t/1000 -> segundos.
        norm = [{"t": r["t"], "o": r["open"], "h": r["high"],
                 "l": r["low"], "c": r["close"]} for r in raw]
        return format_candles(norm)

    @app.get("/tape")
    def tape(limit: int = 50):
        decisions = engine.store.get_decisions(engine.session_id) if engine.session_id else []
        fills = account_provider().get("_fills", [])
        return merge_tape(decisions, fills, limit)

    @app.get("/coins")
    def coins():
        sz = getattr(engine.client, "sz_decimals", {})
        return [{"name": c, "szDecimals": sz[c]} for c in LIQUID_MAJORS if c in sz]
```

> Nota sobre `/candles`: `market_candles` guarda `t` en ms. El endpoint pasa `t` tal cual (ms) a `format_candles`, que lo divide a segundos para Lightweight-Charts. (El test sembró `t=60000` ms → sale `time=60` s.)

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (existentes + 6 nuevos)

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/api.py bot/tests/test_api.py
git commit -m "feat(api): endpoints /account /positions /equity_curve /candles /tape /coins + CORS"
```

---

### Task 6: Snapshot enriquecido (`/state` y `/ws`)

**Files:**
- Modify: `bot/src/hlbot/session_engine.py`, `bot/src/hlbot/api.py`
- Test: `bot/tests/test_api.py`, `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `account_provider()`, `engine.snapshot()`, `engine.client.cfg.testnet`.
- Produces: `engine.snapshot()` añade por coin `"armed": bool` (todas las condiciones cumplidas) y top-level `"mode": "testnet"|"mainnet"`; la API compone `/state` y `/ws` mezclando el snapshot con `account` (resumen), `positions` y `tape_recent`.

- [ ] **Step 1: Escribir los tests que fallan**

En `bot/tests/test_session_engine.py`:
```python
def test_snapshot_has_armed_and_mode():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    snap = eng.snapshot(_flat_ms())
    assert snap["mode"] in ("testnet", "mainnet")
    assert "armed" in snap["coins"]["ETH"]
```
> `FakeClient` no tiene `cfg`; el snapshot debe degradar a `"mainnet"`/`"testnet"` con un getattr seguro (default `testnet`). Ver implementación.

En `bot/tests/test_api.py`:
```python
def test_state_includes_account_and_tape(tmp_path):
    client, _ = _client_with_data(tmp_path)
    r = client.get("/state")
    body = r.json()
    assert "account" in body and "positions" in body and "tape_recent" in body
```

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py::test_snapshot_has_armed_and_mode tests/test_api.py::test_state_includes_account_and_tape -v`
Expected: FAIL

- [ ] **Step 3: Implementar — `session_engine.py`**

En `snapshot()`, dentro del bucle por coin, añade `armed`:
```python
                conds = active.conditions(ms)
                coins[coin] = {
                    "mid": ms.mid,
                    "mode": "trend" if trending else "grid",
                    "triggers": [to_dict(t) for t in active.armed_triggers(ms)],
                    "conditions": [to_dict(c) for c in conds],
                    "armed": all(c.met for c in conds) if conds else False,
                }
```
Y en el `return`, añade `mode` (testnet/mainnet) de forma segura:
```python
        testnet = getattr(getattr(self.client, "cfg", None), "testnet", True)
        return {
            "state": self.state.value,
            "paused": self.paused,
            "mode": "testnet" if testnet else "mainnet",
            "watchlist": self.cfg.watchlist if self.cfg else [],
            "coins": coins,
        }
```

- [ ] **Step 4: Implementar — `api.py`** (componer `/state` y `/ws`)

Añade un helper dentro de `create_app` y úsalo en ambos sitios:
```python
    def _full_snapshot():
        snap = engine.snapshot(market_state_provider())
        acc = dict(account_provider())
        fills = acc.pop("_fills", [])
        acc.pop("_funding", None)
        decisions = engine.store.get_decisions(engine.session_id) if engine.session_id else []
        snap["account"] = acc
        snap["positions"] = acc.get("positions", [])
        snap["tape_recent"] = merge_tape(decisions, fills, limit=20)
        return snap
```
Reemplaza el cuerpo de `/state` por `return _full_snapshot()` y, en el `while` del WebSocket, `await websocket.send_json(_full_snapshot())`.

- [ ] **Step 5: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_session_engine.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/session_engine.py bot/src/hlbot/api.py bot/tests/test_session_engine.py bot/tests/test_api.py
git commit -m "feat(api): snapshot enriquecido (account/positions/tape_recent + armed + mode)"
```

---

## Notas para el ejecutor
- Ejecuta las tareas en orden (dependencias: 4 usa 2; 5 usa 1+2; 6 usa 2+5).
- Validación final en testnet: con el bot corriendo y una sesión activa, `curl localhost:3300/account`, `/positions`, `/state` deben devolver datos reales; confirma de paso las firmas del SDK de `user_fills`/`user_funding` (Task 3).
- Tras 2a, el siguiente plan es **2b (dashboard Next.js)**, que consumirá estos endpoints + el `/ws` enriquecido.
