# Dashboard 2a.2 — Historial y track record: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir fills/funding de forma duradera y exponer endpoints para ver el resultado de cada sesión en detalle y un cómputo global de PnL, separado por modo (testnet vs mainnet).

**Architecture:** Migración idempotente del esquema SQLite (columna `mode` en `sessions`; `tid`/`closed_pnl`/`dir` en `fills`; dedup por índice único). El runner graba fills/funding nuevos (dedup por `tid`) durante el refresco de extras. Funciones puras en `track_record.py` derivan el resumen por sesión y el global por modo desde los datos grabados. Tres endpoints REST de lectura los sirven.

**Tech Stack:** Python 3.11+, `sqlite3`, FastAPI, `pytest` + `httpx`.

## Global Constraints

- **Derivar, no congelar:** los resúmenes se calculan al consultar desde los datos grabados (fuente de verdad). No hay tabla de resultados pre-calculados.
- **Separación por modo:** cada sesión lleva `mode` ("testnet"/"mainnet"); el global se computa por modo y NO se mezclan.
- **Dedup:** fills por `tid` (id de trade de Hyperliquid) vía índice único + `INSERT OR IGNORE`; funding por `fkey`.
- **Migración no destructiva:** `init_schema` añade columnas/índices con `ALTER TABLE`/`CREATE INDEX IF NOT EXISTS` idempotentes (try/except `OperationalError`), preservando `bot/data.db` existente.
- Endpoints de lectura SIN token (como el resto de lecturas del 2a).
- Importes monetarios como `float`.

**Estructura de ficheros (2a.2):**
```
bot/src/hlbot/store.py            # migración + create_session(mode) + record_*_unique + list_sessions/get_session/get_funding
bot/src/hlbot/session_engine.py   # launch pasa mode a create_session
bot/src/hlbot/track_record.py     # NUEVO: session_summary, global_stats (puras)
bot/src/hlbot/main.py             # runner graba fills/funding nuevos (dedup) en extras
bot/src/hlbot/api.py              # endpoints /sessions, /sessions/{id}, /stats/global
bot/tests/test_store.py           # migración + dedup + list/get
bot/tests/test_track_record.py    # NUEVO: puras
bot/tests/test_session_engine.py  # FakeStore.create_session acepta mode; mode en create_session
bot/tests/test_runner.py          # grabación dedup en refresh_account_cache
bot/tests/test_api.py             # endpoints nuevos
```

---

### Task 1: Migración de esquema + `mode` por sesión + read helpers de sesiones

**Files:**
- Modify: `bot/src/hlbot/store.py`, `bot/src/hlbot/session_engine.py`
- Test: `bot/tests/test_store.py`, `bot/tests/test_session_engine.py`

**Interfaces:**
- Produces: `init_schema()` idempotente que añade `sessions.mode`, `fills.tid/closed_pnl/dir`, `funding_payments.fkey` e índices únicos; `Store.create_session(watchlist, capital, mode="testnet") -> int`; `Store.list_sessions(mode: str | None = None) -> list[dict]`; `Store.get_session(session_id) -> dict | None`. Engine `launch` pasa `mode`.

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_store.py`)

```python
def test_init_schema_idempotent_and_adds_columns(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    store.init_schema()  # 2ª vez no debe fallar (migración idempotente)
    with store._conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert "mode" in cols
        fcols = {r[1] for r in conn.execute("PRAGMA table_info(fills)")}
        assert {"tid", "closed_pnl", "dir"} <= fcols

def test_create_session_with_mode_and_list(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    a = store.create_session(["ETH"], 40.0, mode="testnet")
    b = store.create_session(["BTC"], 50.0, mode="mainnet")
    assert store.get_session(a)["mode"] == "testnet"
    testnet_ids = [s["id"] for s in store.list_sessions(mode="testnet")]
    assert a in testnet_ids and b not in testnet_ids
    assert len(store.list_sessions()) == 2  # sin filtro, todas
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py::test_init_schema_idempotent_and_adds_columns tests/test_store.py::test_create_session_with_mode_and_list -v`
Expected: FAIL (mode no existe / create_session no acepta mode)

- [ ] **Step 3: Implementar en `store.py`**

Añade las columnas nuevas a las CREATE TABLE del `SCHEMA` (para BD nuevas): en `sessions` añade `,\n    mode TEXT` antes del cierre `);`; en `fills` añade `,\n    tid TEXT,\n    closed_pnl REAL,\n    dir TEXT` antes del cierre; en `funding_payments` añade `,\n    fkey TEXT` antes del cierre.

Añade una lista de migraciones tras `SCHEMA`:
```python
MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN mode TEXT",
    "ALTER TABLE fills ADD COLUMN tid TEXT",
    "ALTER TABLE fills ADD COLUMN closed_pnl REAL",
    "ALTER TABLE fills ADD COLUMN dir TEXT",
    "ALTER TABLE funding_payments ADD COLUMN fkey TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_tid ON fills(tid)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_funding_fkey ON funding_payments(fkey)",
]
```

Reemplaza `init_schema` para aplicar migraciones idempotentes:
```python
    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            for stmt in MIGRATIONS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # columna/índice ya existe (BD antigua o nueva)
```

Reemplaza `create_session` para aceptar `mode`:
```python
    def create_session(self, watchlist: list[str], capital: float,
                       mode: str = "testnet") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, watchlist, capital, mode) "
                "VALUES (?, ?, ?, ?)",
                (int(time.time()), ",".join(watchlist), capital, mode),
            )
            return int(cur.lastrowid)
```

Añade los read helpers:
```python
    def list_sessions(self, mode: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if mode:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE mode=? ORDER BY id DESC", (mode,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: int) -> dict | None:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return dict(r) if r else None
```

- [ ] **Step 4: Implementar el paso de `mode` en el engine** (`session_engine.py`, en `launch`)

Reemplaza la línea `self.session_id = self.store.create_session(cfg.watchlist, cfg.capital)` por:
```python
        testnet = getattr(getattr(self.client, "cfg", None), "testnet", True)
        self.session_id = self.store.create_session(
            cfg.watchlist, cfg.capital, mode="testnet" if testnet else "mainnet")
```

- [ ] **Step 5: Actualizar el FakeStore del test del engine** (`bot/tests/test_session_engine.py`)

En la clase `FakeStore`, cambia la firma de `create_session` para aceptar `mode`:
```python
    def create_session(self, watchlist, capital, mode="testnet"): return self.sid
```

- [ ] **Step 6: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py tests/test_session_engine.py -v`
Expected: PASS (incluidos los nuevos; los del engine siguen verdes)

- [ ] **Step 7: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/store.py bot/src/hlbot/session_engine.py bot/tests/test_store.py bot/tests/test_session_engine.py
git commit -m "feat(track): migracion mode + tid/closed_pnl/dir + create_session(mode) + list/get_session"
```

---

### Task 2: Grabación duradera con dedup (`record_fill_unique`, `record_funding_unique`, `get_funding`)

**Files:**
- Modify: `bot/src/hlbot/store.py`
- Test: `bot/tests/test_store.py`

**Interfaces:**
- Consumes: índices únicos de Task 1.
- Produces: `Store.record_fill_unique(session_id, tid, ts, coin, side, dir, price, size, fee, closed_pnl) -> None` (idempotente por `tid`); `Store.record_funding_unique(session_id, fkey, ts, coin, amount) -> None` (idempotente por `fkey`); `Store.get_funding(session_id) -> list[dict]`. `get_fills` (ya existe) ahora devuelve también `tid/closed_pnl/dir` (es `SELECT *`).

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_store.py`)

```python
def test_record_fill_unique_dedups_by_tid(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    for _ in range(2):  # mismo tid dos veces -> una fila
        store.record_fill_unique(sid, "tid1", 100, "ETH", "B", "Close Long",
                                 3000.0, 0.004, 0.0015, 0.02)
    fills = store.get_fills(sid)
    assert len(fills) == 1
    assert fills[0]["closed_pnl"] == 0.02 and fills[0]["dir"] == "Close Long"

def test_record_funding_unique_dedups(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    for _ in range(2):
        store.record_funding_unique(sid, "fk1", 100, "ETH", -0.001)
    f = store.get_funding(sid)
    assert len(f) == 1 and f[0]["amount"] == -0.001
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py::test_record_fill_unique_dedups_by_tid tests/test_store.py::test_record_funding_unique_dedups -v`
Expected: FAIL (`AttributeError: record_fill_unique`)

- [ ] **Step 3: Implementar en `store.py`** (añadir métodos a la clase)

```python
    def record_fill_unique(self, session_id: int, tid: str, ts: int, coin: str,
                           side: str, dir: str, price: float, size: float,
                           fee: float, closed_pnl: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO fills "
                "(session_id, tid, ts, coin, side, dir, price, size, fee, closed_pnl) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, tid, ts, coin, side, dir, price, size, fee, closed_pnl),
            )

    def record_funding_unique(self, session_id: int, fkey: str, ts: int,
                              coin: str, amount: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO funding_payments "
                "(session_id, fkey, ts, coin, amount) VALUES (?, ?, ?, ?, ?)",
                (session_id, fkey, ts, coin, amount),
            )

    def get_funding(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM funding_payments WHERE session_id=? ORDER BY id",
                (session_id,)).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/store.py bot/tests/test_store.py
git commit -m "feat(track): record_fill_unique/record_funding_unique (dedup) + get_funding"
```

---

### Task 3: Funciones puras de agregación (`track_record.py`)

**Files:**
- Create: `bot/src/hlbot/track_record.py`
- Test: `bot/tests/test_track_record.py`

**Interfaces:**
- Consumes: nada (puras).
- Produces: `session_summary(session_row: dict, fills: list[dict], funding: list[dict], pnl_snapshots: list[dict]) -> dict` → `{id, mode, started_at, ended_at, duration_s, capital, n_trades, wins, realized_pnl, fees, funding, win_rate, net_pnl}`. `global_stats(summaries: list[dict]) -> dict` → `{testnet: {...}, mainnet: {...}}` con `{n_sessions, realized_pnl, fees, funding, net_pnl, win_rate, best_session, worst_session}`.

- [ ] **Step 1: Escribir los tests que fallan** (`bot/tests/test_track_record.py`)

```python
from hlbot.track_record import session_summary, global_stats

SESS = {"id": 1, "mode": "testnet", "started_at": 1000, "ended_at": 1600, "capital": 40.0}
FILLS = [
    {"dir": "Close Long", "closed_pnl": 0.05, "fee": 0.0015},
    {"dir": "Close Short", "closed_pnl": -0.02, "fee": 0.0010},
    {"dir": "Open Long", "closed_pnl": 0.0, "fee": 0.0012},
]
FUND = [{"amount": -0.001}, {"amount": 0.0003}]
SNAPS = [{"ts": 1100, "total_pnl": 0.01}, {"ts": 1500, "total_pnl": 0.03}]

def test_session_summary():
    s = session_summary(SESS, FILLS, FUND, SNAPS)
    assert s["id"] == 1 and s["mode"] == "testnet"
    assert s["duration_s"] == 600
    assert s["n_trades"] == 2                       # solo "Close"
    assert s["wins"] == 1
    assert abs(s["realized_pnl"] - 0.03) < 1e-9     # 0.05 - 0.02
    assert abs(s["fees"] - (0.0015 + 0.0010 + 0.0012)) < 1e-9
    assert abs(s["funding"] - (-0.001 + 0.0003)) < 1e-9
    assert abs(s["win_rate"] - 0.5) < 1e-9
    assert s["net_pnl"] == 0.03                     # último snapshot

def test_session_summary_no_data():
    s = session_summary({"id": 2, "mode": "mainnet", "started_at": 1, "ended_at": None,
                         "capital": 50.0}, [], [], [])
    assert s["n_trades"] == 0 and s["win_rate"] == 0.0
    assert s["net_pnl"] == 0.0 and s["duration_s"] is None

def test_global_stats_separates_modes():
    summaries = [
        {"mode": "testnet", "n_trades": 2, "wins": 1, "realized_pnl": 0.03, "fees": 0.004,
         "funding": -0.001, "net_pnl": 0.02, "id": 1},
        {"mode": "testnet", "n_trades": 1, "wins": 1, "realized_pnl": 0.10, "fees": 0.001,
         "funding": 0.0, "net_pnl": 0.09, "id": 2},
        {"mode": "mainnet", "n_trades": 1, "wins": 0, "realized_pnl": -0.05, "fees": 0.001,
         "funding": 0.0, "net_pnl": -0.06, "id": 3},
    ]
    g = global_stats(summaries)
    assert g["testnet"]["n_sessions"] == 2
    assert abs(g["testnet"]["realized_pnl"] - 0.13) < 1e-9
    assert abs(g["testnet"]["win_rate"] - (2/3)) < 1e-9   # 2 wins / 3 trades
    assert g["testnet"]["best_session"] == 2 and g["testnet"]["worst_session"] == 1
    assert g["mainnet"]["n_sessions"] == 1
    assert abs(g["mainnet"]["realized_pnl"] - (-0.05)) < 1e-9
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: FAIL (`ModuleNotFoundError: hlbot.track_record`)

- [ ] **Step 3: Implementar `track_record.py`**

```python
from __future__ import annotations


def session_summary(session_row: dict, fills: list[dict], funding: list[dict],
                    pnl_snapshots: list[dict]) -> dict:
    closes = [f for f in fills if "Close" in (f.get("dir") or "")]
    realized = sum(float(f.get("closed_pnl") or 0) for f in closes)
    fees = sum(float(f.get("fee") or 0) for f in fills)
    fund = sum(float(f.get("amount") or 0) for f in funding)
    wins = sum(1 for f in closes if float(f.get("closed_pnl") or 0) > 0)
    win_rate = (wins / len(closes)) if closes else 0.0
    net_pnl = float(pnl_snapshots[-1]["total_pnl"]) if pnl_snapshots else 0.0
    started = session_row.get("started_at")
    ended = session_row.get("ended_at")
    duration = (ended - started) if (started and ended) else None
    return {
        "id": session_row.get("id"),
        "mode": session_row.get("mode"),
        "started_at": started,
        "ended_at": ended,
        "duration_s": duration,
        "capital": session_row.get("capital"),
        "n_trades": len(closes),
        "wins": wins,
        "realized_pnl": realized,
        "fees": fees,
        "funding": fund,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
    }


def global_stats(summaries: list[dict]) -> dict:
    out: dict = {}
    for mode in ("testnet", "mainnet"):
        ms = [s for s in summaries if s.get("mode") == mode]
        trades = sum(s.get("n_trades", 0) for s in ms)
        wins = sum(s.get("wins", 0) for s in ms)
        best = max(ms, key=lambda s: s.get("net_pnl", 0), default=None)
        worst = min(ms, key=lambda s: s.get("net_pnl", 0), default=None)
        out[mode] = {
            "n_sessions": len(ms),
            "realized_pnl": sum(s.get("realized_pnl", 0) for s in ms),
            "fees": sum(s.get("fees", 0) for s in ms),
            "funding": sum(s.get("funding", 0) for s in ms),
            "net_pnl": sum(s.get("net_pnl", 0) for s in ms),
            "win_rate": (wins / trades) if trades else 0.0,
            "best_session": best["id"] if best else None,
            "worst_session": worst["id"] if worst else None,
        }
    return out
```

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_track_record.py -v`
Expected: PASS (3)

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/track_record.py bot/tests/test_track_record.py
git commit -m "feat(track): track_record.py (session_summary, global_stats por modo)"
```

---

### Task 4: El runner graba fills/funding nuevos (dedup) durante extras

**Files:**
- Modify: `bot/src/hlbot/main.py`
- Test: `bot/tests/test_runner.py`

**Interfaces:**
- Consumes: `store.record_fill_unique`, `store.record_funding_unique` (Task 2); `client.user_fills`, `client.user_funding`.
- Produces: `refresh_account_cache(client, engine, prev, fetch_extras, store=None)` — cuando `store` y `engine.session_id`, en el path de extras graba (dedup) los fills y funding de la sesión. La firma añade `store=None` al final (retrocompatible con los tests existentes).

- [ ] **Step 1: Escribir el test que falla** (añadir a `bot/tests/test_runner.py`)

```python
from hlbot.store import Store

def test_refresh_records_fills_dedup(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["BTC"], 40.0, mode="testnet")

    class _Eng2:
        session_start_value = 50.0
        session_started_at = 0
        session_id = sid
        class cfg:
            class limits:
                max_open_positions = 4

    class _Client2:
        def user_state(self):
            return {"marginSummary": {"accountValue": "49"}, "assetPositions": []}
        def user_fills(self):
            return [{"tid": 7, "time": 1000, "coin": "BTC", "side": "B",
                     "dir": "Close Long", "px": "67550", "sz": "0.0002",
                     "fee": "0.0015", "closedPnl": "0.02"}]
        def user_funding(self, start_ms):
            return [{"time": 1000, "hash": "h1", "delta": {"usdc": "-0.001", "coin": "BTC"}}]

    c = _Client2()
    refresh_account_cache(c, _Eng2(), {}, fetch_extras=True, store=store)
    refresh_account_cache(c, _Eng2(), {}, fetch_extras=True, store=store)  # 2ª vez: dedup
    assert len(store.get_fills(sid)) == 1
    assert store.get_fills(sid)[0]["closed_pnl"] == 0.02
    assert len(store.get_funding(sid)) == 1
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py::test_refresh_records_fills_dedup -v`
Expected: FAIL (`refresh_account_cache() got unexpected keyword 'store'` o no graba)

- [ ] **Step 3: Implementar en `main.py`**

Cambia la firma de `refresh_account_cache` añadiendo `store=None` al final, y dentro del bloque `if fetch_extras:`, tras obtener `all_fills` y `funding`, graba en el store (dedup) cuando hay store y sesión. La versión completa de la función:
```python
def refresh_account_cache(client, engine, prev: dict, fetch_extras: bool,
                          store=None) -> dict:
    try:
        ch = client.user_state()
    except Exception as e:
        print(f"[account_cache] user_state error: {e}", flush=True)
        return prev
    session_start_ms = int((engine.session_started_at or 0) * 1000)
    fills = prev.get("_fills", [])
    funding_total = prev.get("_funding", 0.0)
    if fetch_extras:
        try:
            all_fills = client.user_fills()
            fills = [f for f in all_fills if int(f.get("time", 0) or 0) >= session_start_ms]
            funding = client.user_funding(session_start_ms)
            funding_total = sum(float(f.get("delta", {}).get("usdc", 0) or 0) for f in funding)
            if store is not None and engine.session_id is not None:
                _record_extras(store, engine.session_id, fills, funding)
        except Exception as e:
            print(f"[account_cache] extras error: {e}", flush=True)
    max_open = engine.cfg.limits.max_open_positions if engine.cfg else 0
    acc = compose_account(ch, fills, funding_total, engine.session_start_value, max_open)
    acc["_fills"] = fills
    acc["_funding"] = funding_total
    return acc


def _record_extras(store, session_id: int, fills: list[dict], funding: list[dict]) -> None:
    for f in fills:
        tid = str(f.get("tid") if f.get("tid") is not None else f.get("hash", ""))
        if not tid:
            continue
        store.record_fill_unique(
            session_id, tid, int(f.get("time", 0) or 0) // 1000, f.get("coin"),
            f.get("side", ""), f.get("dir", ""), float(f.get("px", 0) or 0),
            float(f.get("sz", 0) or 0), float(f.get("fee", 0) or 0),
            float(f.get("closedPnl", 0) or 0))
    for fp in funding:
        delta = fp.get("delta", {}) or {}
        fkey = str(fp.get("hash") or f"{fp.get('time','')}-{delta.get('coin','')}")
        store.record_funding_unique(
            session_id, fkey, int(fp.get("time", 0) or 0) // 1000,
            delta.get("coin", ""), float(delta.get("usdc", 0) or 0))
```

Y en `_trade_loop`, pasa `store` a la llamada de `refresh_account_cache`:
```python
                cache_holder["v"] = refresh_account_cache(
                    client, engine, cache_holder["v"],
                    fetch_extras=(loop_count % ACCOUNT_EXTRAS_EVERY == 0), store=store)
```

> Nota SDK: los campos de `user_fills` (`tid`, `dir`, `px`, `sz`, `fee`, `closedPnl`, `time`) y de `user_funding` (`delta.usdc`, `delta.coin`, `time`, `hash`) se validan EN VIVO en testnet (las credenciales están presentes). Si algún nombre difiere, ajusta `_record_extras` manteniendo la firma de `refresh_account_cache`.

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd bot && .venv/bin/python -m pytest tests/test_runner.py -v`
Expected: PASS (incluido el nuevo; los existentes siguen verdes — `store` tiene default None)

- [ ] **Step 5: Smoke import + suite + commit**

```bash
cd bot && .venv/bin/python -c "import hlbot.main; print('ok')"
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/main.py bot/tests/test_runner.py
git commit -m "feat(track): el runner graba fills/funding nuevos (dedup) en extras"
```

---

### Task 5: Endpoints `/sessions`, `/sessions/{id}`, `/stats/global`

**Files:**
- Modify: `bot/src/hlbot/api.py`
- Test: `bot/tests/test_api.py`

**Interfaces:**
- Consumes: `track_record.session_summary`, `track_record.global_stats`; `engine.store.list_sessions/get_session/get_fills/get_funding/get_pnl_snapshots/get_decisions`.
- Produces: `GET /sessions?mode=`, `GET /sessions/{session_id}`, `GET /stats/global` (lectura, sin token).

- [ ] **Step 1: Escribir los tests que fallan** (añadir a `bot/tests/test_api.py`)

```python
def _seed_two_sessions(tmp_path):
    from hlbot.store import Store
    store = Store(str(tmp_path / "tr.db")); store.init_schema()
    s1 = store.create_session(["ETH"], 40.0, mode="testnet")
    store.record_fill_unique(s1, "t1", 100, "ETH", "B", "Close Long", 3000, 0.004, 0.0015, 0.05)
    store.record_pnl_snapshot(s1, 0.03)
    s2 = store.create_session(["BTC"], 50.0, mode="mainnet")
    store.record_fill_unique(s2, "t2", 200, "BTC", "A", "Close Short", 67000, 0.0002, 0.001, -0.04)
    store.record_pnl_snapshot(s2, -0.05)
    return store, s1, s2

def _api_with_store(store):
    from hlbot.api import create_app
    from hlbot.session_engine import SessionEngine
    from test_session_engine import FakeClient
    engine = SessionEngine(FakeClient(), store)
    return TestClient(create_app(engine, TOKEN, lambda: {}, lambda: {}))

def test_sessions_list_filter_by_mode(tmp_path):
    store, s1, s2 = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    alls = client.get("/sessions").json()
    assert {s["id"] for s in alls} == {s1, s2}
    testnet = client.get("/sessions?mode=testnet").json()
    assert [s["id"] for s in testnet] == [s1]
    assert testnet[0]["realized_pnl"] == 0.05

def test_session_detail(tmp_path):
    store, s1, _ = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    body = client.get(f"/sessions/{s1}").json()
    assert body["summary"]["id"] == s1
    assert len(body["trades"]) == 1 and body["trades"][0]["closed_pnl"] == 0.05
    assert "equity_curve" in body and "decisions" in body

def test_stats_global_separates_modes(tmp_path):
    store, _, _ = _seed_two_sessions(tmp_path)
    client = _api_with_store(store)
    g = client.get("/stats/global").json()
    assert g["testnet"]["n_sessions"] == 1 and g["mainnet"]["n_sessions"] == 1
    assert abs(g["testnet"]["realized_pnl"] - 0.05) < 1e-9
    assert abs(g["mainnet"]["realized_pnl"] - (-0.04)) < 1e-9
```

- [ ] **Step 2: Ejecutar y verificar que fallan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_api.py -k "sessions or stats_global" -v`
Expected: FAIL (404)

- [ ] **Step 3: Implementar en `api.py`**

Import nuevo arriba: `from hlbot.track_record import session_summary, global_stats`.

Añade un helper y los endpoints dentro de `create_app` (junto a los demás GET):
```python
    def _summary_for(session_row: dict) -> dict:
        sid = session_row["id"]
        return session_summary(
            session_row,
            engine.store.get_fills(sid),
            engine.store.get_funding(sid),
            engine.store.get_pnl_snapshots(sid),
        )

    @app.get("/sessions")
    def sessions(mode: str | None = None):
        return [_summary_for(s) for s in engine.store.list_sessions(mode)]

    @app.get("/sessions/{session_id}")
    def session_detail(session_id: int):
        s = engine.store.get_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="sesion no encontrada")
        return {
            "summary": _summary_for(s),
            "trades": engine.store.get_fills(session_id),
            "equity_curve": engine.store.get_pnl_snapshots(session_id),
            "decisions": engine.store.get_decisions(session_id),
        }

    @app.get("/stats/global")
    def stats_global():
        summaries = [_summary_for(s) for s in engine.store.list_sessions()]
        return global_stats(summaries)
```

- [ ] **Step 4: Ejecutar y verificar que pasan**

Run: `cd bot && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (existentes + 3 nuevos)

- [ ] **Step 5: Suite completa + commit**

```bash
cd bot && .venv/bin/python -m pytest -q
git add bot/src/hlbot/api.py bot/tests/test_api.py
git commit -m "feat(track): endpoints /sessions, /sessions/{id}, /stats/global"
```

---

## Notas para el ejecutor
- Orden por dependencias: 1 (esquema/mode) → 2 (grabación) → 3 (puras) → 4 (runner usa 2) → 5 (endpoints usan 2+3).
- Validación en testnet: con el bot corriendo y una sesión, tras unos minutos `curl localhost:3300/sessions` y `/stats/global` deben mostrar la sesión testnet con sus fills; confirma de paso las formas del SDK de `user_fills`/`user_funding` (Task 4).
- Tras 2a.2, el siguiente plan es **2b (dashboard Next.js)**: terminal en vivo + vista Past Sessions consumiendo estos endpoints + los del 2a.
