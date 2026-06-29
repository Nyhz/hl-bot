# Sub-proyecto 1 — Núcleo del bot + API: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el núcleo Python del bot de Hyperliquid — motor de sesiones, estrategias (grid + overlay de tendencia), riesgo, persistencia SQLite y una API FastAPI (REST + WebSocket) — validado en testnet, que produce datos reales de triggers/condiciones/decisiones/posiciones que el dashboard podrá visualizar.

**Architecture:** Componentes con responsabilidad única detrás de interfaces claras. Funciones puras para indicadores y estrategias (deterministas, fáciles de testear); un `SessionEngine` que orquesta estrategias + riesgo + cliente + store mediante una máquina de estados; un `HLClient` que envuelve el SDK oficial; una capa `api` FastAPI que expone lectura, control y stream en vivo. La lógica determinista se testea con datos sintéticos; el `HLClient` se valida con tests de integración contra testnet.

**Tech Stack:** Python 3.11+, `hyperliquid-python-sdk`, `eth-account`, `pandas` (indicadores), `fastapi` + `uvicorn[standard]` (API/WS), `sqlite3` (stdlib), `pytest` + `httpx` (tests), `python-dotenv`.

## Global Constraints

- Mínimo de orden: **$10 de notional** (excepción: reduce-only que cierra posición). Toda orden de apertura debe validar `price * size >= 10.0`.
- **Sin builder fee:** ninguna orden pasa parámetro de builder/builder code.
- Precisión de precio (perps): máx 5 cifras significativas y máx `6 - szDecimals` decimales. Tamaño: redondeado a `szDecimals` del activo.
- **Testnet primero:** por defecto `HL_TESTNET=true` → `constants.TESTNET_API_URL`. Mainnet solo con flag explícito.
- Credenciales (`HL_SECRET_KEY` de la API wallet, `HL_ACCOUNT_ADDRESS` master, `CONTROL_TOKEN`) se leen de `.env` (en `.gitignore`); nunca se commitean.
- Estrategia maker-only en el grid: órdenes límite con TIF `Alo` (post-only).
- Las funciones de cara al API serializan a dict JSON-friendly (enums como `str`).
- Commits frecuentes: un commit por tarea como mínimo.

**Estructura de ficheros (sub-proyecto 1, dentro de `bot/`):**

```
bot/
├── pyproject.toml          # deps + config de pytest
├── .env.example            # plantilla de credenciales (sin valores reales)
├── src/hlbot/
│   ├── __init__.py
│   ├── config.py           # Config: testnet/mainnet, credenciales, control token
│   ├── models.py           # dataclasses + enums del dominio
│   ├── indicators.py       # ema, atr, adx (funciones puras sobre listas)
│   ├── store.py            # Store: persistencia SQLite
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py         # Protocol Strategy
│   │   ├── grid.py         # GridStrategy
│   │   └── trend.py        # TrendOverlayStrategy
│   ├── risk.py             # RiskManager
│   ├── hl_client.py        # HLClient: envoltorio del SDK + helpers de precisión
│   ├── session_engine.py   # SessionEngine: máquina de estados
│   └── api.py              # FastAPI app (REST + WebSocket)
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_models.py
    ├── test_indicators.py
    ├── test_store.py
    ├── test_grid.py
    ├── test_trend.py
    ├── test_risk.py
    ├── test_precision.py
    ├── test_session_engine.py
    ├── test_api.py
    └── test_hl_client_testnet.py   # integración (se salta sin credenciales)
```

---

### Task 1: Scaffolding del proyecto y configuración

**Files:**
- Create: `bot/pyproject.toml`
- Create: `bot/.env.example`
- Create: `bot/src/hlbot/__init__.py` (vacío)
- Create: `bot/src/hlbot/config.py`
- Create: `bot/tests/conftest.py`
- Test: `bot/tests/test_config.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Config` dataclass con campos `testnet: bool`, `account_address: str | None`, `secret_key: str | None`, `control_token: str`, `db_path: str`; método `Config.from_env() -> Config`; propiedad `Config.base_url -> str`.

- [ ] **Step 1: Crear `pyproject.toml`**

```toml
[project]
name = "hlbot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "hyperliquid-python-sdk",
    "eth-account",
    "pandas",
    "fastapi",
    "uvicorn[standard]",
    "python-dotenv",
]

[project.optional-dependencies]
dev = ["pytest", "httpx"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Crear `.env.example`**

```bash
# Copia a .env y rellena. .env está en .gitignore.
HL_TESTNET=true
HL_ACCOUNT_ADDRESS=
HL_SECRET_KEY=
CONTROL_TOKEN=cambia-esto-por-un-token-local
DB_PATH=data.db
```

- [ ] **Step 3: Escribir el test que falla** en `bot/tests/test_config.py`

```python
from hlbot.config import Config

def test_defaults_to_testnet(monkeypatch):
    monkeypatch.delenv("HL_TESTNET", raising=False)
    cfg = Config.from_env()
    assert cfg.testnet is True
    assert cfg.base_url == "https://api.hyperliquid-testnet.xyz"

def test_mainnet_when_flag_false(monkeypatch):
    monkeypatch.setenv("HL_TESTNET", "false")
    cfg = Config.from_env()
    assert cfg.testnet is False
    assert cfg.base_url == "https://api.hyperliquid.xyz"

def test_reads_credentials(monkeypatch):
    monkeypatch.setenv("HL_ACCOUNT_ADDRESS", "0xabc")
    monkeypatch.setenv("CONTROL_TOKEN", "tok")
    cfg = Config.from_env()
    assert cfg.account_address == "0xabc"
    assert cfg.control_token == "tok"
```

- [ ] **Step 4: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.config'`)

- [ ] **Step 5: Implementar `config.py`**

```python
from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


@dataclass
class Config:
    testnet: bool = True
    account_address: str | None = None
    secret_key: str | None = None
    control_token: str = "change-me"
    db_path: str = "data.db"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            testnet=os.getenv("HL_TESTNET", "true").lower() != "false",
            account_address=os.getenv("HL_ACCOUNT_ADDRESS") or None,
            secret_key=os.getenv("HL_SECRET_KEY") or None,
            control_token=os.getenv("CONTROL_TOKEN", "change-me"),
            db_path=os.getenv("DB_PATH", "data.db"),
        )

    @property
    def base_url(self) -> str:
        return TESTNET_URL if self.testnet else MAINNET_URL
```

- [ ] **Step 6: Crear `conftest.py`** (vacío por ahora, asegura descubrimiento de `src`)

```python
# Fixtures compartidas se añadirán en tareas posteriores.
```

- [ ] **Step 7: Instalar y ejecutar tests**

Run: `cd bot && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add bot/pyproject.toml bot/.env.example bot/src/hlbot/__init__.py bot/src/hlbot/config.py bot/tests/conftest.py bot/tests/test_config.py
git commit -m "feat(bot): scaffolding y configuracion testnet/mainnet"
```

---

### Task 2: Modelos del dominio

**Files:**
- Create: `bot/src/hlbot/models.py`
- Test: `bot/tests/test_models.py`

**Interfaces:**
- Consumes: nada.
- Produces: enums `SessionState`, `Side`, `ActionType`; dataclasses `Candle`, `MarketState`, `Trigger`, `Condition`, `Decision`, `RiskLimits`, `SessionConfig`, `Position`; función `to_dict(obj) -> dict` que serializa dataclasses (enums como `str`).

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_models.py`

```python
from hlbot.models import (
    SessionState, Side, ActionType, Candle, MarketState,
    Trigger, Condition, Decision, RiskLimits, SessionConfig, to_dict,
)

def test_enums_are_strings():
    assert SessionState.IDLE == "idle"
    assert Side.BUY == "buy"
    assert ActionType.PLACE_LIMIT == "place_limit"

def test_to_dict_serializes_enums():
    t = Trigger(coin="ETH", level=3000.0, side=Side.BUY, action="place_limit",
                description="compra maker")
    d = to_dict(t)
    assert d["side"] == "buy"
    assert d["level"] == 3000.0

def test_session_config_defaults():
    limits = RiskLimits(max_position_notional=15.0, max_open_positions=3,
                        max_leverage=2.0, daily_loss_limit=5.0, total_loss_limit=20.0)
    cfg = SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits)
    assert cfg.grid_n == 10
    assert cfg.ema_fast == 9 and cfg.ema_slow == 21
    assert cfg.adx_threshold == 25.0
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.models'`)

- [ ] **Step 3: Implementar `models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum


class SessionState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    ACTIVE = "active"
    CLOSING = "closing"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ActionType(str, Enum):
    PLACE_LIMIT = "place_limit"
    PLACE_MARKET = "place_market"
    SET_STOP = "set_stop"
    CANCEL = "cancel"
    CLOSE = "close"


@dataclass
class Candle:
    t: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketState:
    coin: str
    mid: float
    candles: list[Candle] = field(default_factory=list)
    funding_rate: float | None = None


@dataclass
class Trigger:
    coin: str
    level: float
    side: Side
    action: str
    description: str


@dataclass
class Condition:
    name: str
    value: float
    threshold: float
    met: bool


@dataclass
class Decision:
    coin: str
    action: ActionType
    side: Side | None = None
    price: float | None = None
    size: float | None = None
    reduce_only: bool = False
    reason: str = ""


@dataclass
class RiskLimits:
    max_position_notional: float
    max_open_positions: int
    max_leverage: float
    daily_loss_limit: float
    total_loss_limit: float


@dataclass
class SessionConfig:
    watchlist: list[str]
    capital: float
    limits: RiskLimits
    grid_n: int = 10
    grid_range_pct: float = 0.03
    grid_spacing_pct: float = 0.003
    ema_fast: int = 9
    ema_slow: int = 21
    adx_period: int = 14
    adx_threshold: float = 25.0
    atr_period: int = 14
    atr_stop_mult: float = 2.0


@dataclass
class Position:
    coin: str
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0


def _convert(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return to_dict(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def to_dict(obj) -> dict:
    return {k: _convert(v) for k, v in asdict(obj).items()}
```

> Nota: `asdict` ya recorre dataclasses anidados; `_convert` re-mapea enums a `str`. El doble paso es seguro porque `asdict` deja los enums como instancias `Enum` (que aquí re-convertimos).

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/models.py bot/tests/test_models.py
git commit -m "feat(bot): modelos del dominio (enums + dataclasses + to_dict)"
```

---

### Task 3: Indicadores técnicos (puros)

**Files:**
- Create: `bot/src/hlbot/indicators.py`
- Test: `bot/tests/test_indicators.py`

**Interfaces:**
- Consumes: nada.
- Produces: `ema(values: list[float], period: int) -> list[float]`; `atr(high, low, close, period=14) -> list[float]`; `adx(high, low, close, period=14) -> list[float]`. Todas devuelven listas de la misma longitud que la entrada.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_indicators.py`

```python
import math
from hlbot.indicators import ema, atr, adx

def test_ema_of_constant_is_constant():
    assert all(abs(x - 5.0) < 1e-9 for x in ema([5.0] * 10, 3))

def test_ema_known_values():
    # span=2 -> alpha=2/3; e0=1, e1=1.6667, e2=2.5556
    out = ema([1.0, 2.0, 3.0], 2)
    assert abs(out[0] - 1.0) < 1e-6
    assert abs(out[1] - 1.66667) < 1e-4
    assert abs(out[2] - 2.55556) < 1e-4

def test_atr_is_positive():
    highs = [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20]
    lows = [9, 10, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 16, 18, 19]
    closes = [9.5, 10.5, 11.5, 10.5, 12.5, 13.5, 12.5, 14.5, 15.5, 14.5, 16.5, 17.5, 16.5, 18.5, 19.5]
    out = atr(highs, lows, closes, 14)
    assert out[-1] > 0

def test_adx_in_range_and_high_in_strong_trend():
    # tendencia alcista fuerte -> ADX alto
    closes = [float(i) for i in range(1, 41)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    out = adx(highs, lows, closes, 14)
    last = out[-1]
    assert 0.0 <= last <= 100.0
    assert last > 25.0  # mercado en tendencia clara
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_indicators.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.indicators'`)

- [ ] **Step 3: Implementar `indicators.py`**

```python
from __future__ import annotations
import pandas as pd


def ema(values: list[float], period: int) -> list[float]:
    s = pd.Series(values, dtype="float64")
    return s.ewm(span=period, adjust=False).mean().tolist()


def _true_range(high, low, close) -> pd.Series:
    h = pd.Series(high, dtype="float64")
    l = pd.Series(low, dtype="float64")
    c = pd.Series(close, dtype="float64")
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr


def atr(high, low, close, period: int = 14) -> list[float]:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False).mean().tolist()


def adx(high, low, close, period: int = 14) -> list[float]:
    h = pd.Series(high, dtype="float64")
    l = pd.Series(low, dtype="float64")
    up = h.diff()
    down = -l.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = _true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    denom = (plus_di + minus_di).replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx_ = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx_.fillna(0.0).tolist()
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_indicators.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/indicators.py bot/tests/test_indicators.py
git commit -m "feat(bot): indicadores EMA/ATR/ADX"
```

---

### Task 4: Persistencia SQLite (`Store`)

**Files:**
- Create: `bot/src/hlbot/store.py`
- Test: `bot/tests/test_store.py`

**Interfaces:**
- Consumes: nada (usa `sqlite3` stdlib).
- Produces: clase `Store(db_path: str)` con `init_schema()`, `create_session(watchlist: list[str], capital: float) -> int`, `record_decision(session_id, coin, action, reason)`, `record_fill(session_id, coin, side, price, size, fee)`, `record_pnl_snapshot(session_id, total_pnl)`, `get_decisions(session_id) -> list[dict]`, `get_fills(session_id) -> list[dict]`.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_store.py`

```python
from hlbot.store import Store

def test_create_and_query_session(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH", "BTC"], 40.0)
    assert isinstance(sid, int)

def test_record_and_get_decision(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_decision(sid, "ETH", "place_limit", "grid rung 3000")
    rows = store.get_decisions(sid)
    assert len(rows) == 1
    assert rows[0]["coin"] == "ETH"
    assert rows[0]["reason"] == "grid rung 3000"

def test_record_and_get_fill(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    store.record_fill(sid, "ETH", "buy", 3000.0, 0.0034, 0.0015)
    rows = store.get_fills(sid)
    assert len(rows) == 1
    assert rows[0]["price"] == 3000.0
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.store'`)

- [ ] **Step 3: Implementar `store.py`**

```python
from __future__ import annotations
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    watchlist TEXT NOT NULL,
    capital REAL NOT NULL,
    ended_at INTEGER
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    coin TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    fee REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    total_pnl REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS funding_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    coin TEXT NOT NULL,
    amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS market_candles (
    coin TEXT NOT NULL,
    interval TEXT NOT NULL,
    t INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (coin, interval, t)
);
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def create_session(self, watchlist: list[str], capital: float) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, watchlist, capital) VALUES (?, ?, ?)",
                (int(time.time()), ",".join(watchlist), capital),
            )
            return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET ended_at=? WHERE id=?",
                         (int(time.time()), session_id))

    def record_decision(self, session_id: int, coin: str, action: str, reason: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO decisions (session_id, ts, coin, action, reason) VALUES (?, ?, ?, ?, ?)",
                (session_id, int(time.time()), coin, action, reason),
            )

    def record_fill(self, session_id: int, coin: str, side: str,
                    price: float, size: float, fee: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO fills (session_id, ts, coin, side, price, size, fee) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, int(time.time()), coin, side, price, size, fee),
            )

    def record_pnl_snapshot(self, session_id: int, total_pnl: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pnl_snapshots (session_id, ts, total_pnl) VALUES (?, ?, ?)",
                (session_id, int(time.time()), total_pnl),
            )

    def record_risk_event(self, session_id: int, kind: str, detail: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO risk_events (session_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                (session_id, int(time.time()), kind, detail),
            )

    def get_decisions(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_fills(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM fills WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/store.py bot/tests/test_store.py
git commit -m "feat(bot): persistencia SQLite (Store + esquema)"
```

---

### Task 5: Interfaz `Strategy` y `GridStrategy`

**Files:**
- Create: `bot/src/hlbot/strategy/__init__.py` (vacío)
- Create: `bot/src/hlbot/strategy/base.py`
- Create: `bot/src/hlbot/strategy/grid.py`
- Test: `bot/tests/test_grid.py`

**Interfaces:**
- Consumes: `models` (`MarketState`, `Trigger`, `Condition`, `Decision`, `Side`, `ActionType`, `SessionConfig`).
- Produces: `Protocol Strategy` con `evaluate(ms) -> list[Decision]`, `armed_triggers(ms) -> list[Trigger]`, `conditions(ms) -> list[Condition]`. `GridStrategy(cfg)` con `set_anchor(mid: float)` (fija `lower`, `upper`, `levels`) y los tres métodos del protocolo.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_grid.py`

```python
from hlbot.models import MarketState, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.grid import GridStrategy

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def test_anchor_sets_symmetric_bounds():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    assert abs(g.lower - 2940.0) < 1e-6
    assert abs(g.upper - 3060.0) < 1e-6
    assert len(g.levels) == 5  # grid_n + 1

def test_triggers_buys_below_sells_above():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3000.0)
    trs = g.armed_triggers(ms)
    buys = [t for t in trs if t.side == Side.BUY]
    sells = [t for t in trs if t.side == Side.SELL]
    assert all(t.level < 3000.0 for t in buys)
    assert all(t.level > 3000.0 for t in sells)

def test_evaluate_range_exit_when_price_below_lower():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=2900.0)  # por debajo de lower=2940
    decisions = g.evaluate(ms)
    assert len(decisions) == 1
    assert decisions[0].action == ActionType.CLOSE
    assert decisions[0].reduce_only is True

def test_evaluate_places_maker_orders_in_range():
    g = GridStrategy(_cfg())
    g.set_anchor(3000.0)
    ms = MarketState(coin="ETH", mid=3000.0)
    decisions = g.evaluate(ms)
    assert all(d.action == ActionType.PLACE_LIMIT for d in decisions)
    assert all(d.price * d.size >= 10.0 for d in decisions)  # min notional
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_grid.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.strategy.grid'`)

- [ ] **Step 3: Implementar `base.py`**

```python
from __future__ import annotations
from typing import Protocol
from hlbot.models import MarketState, Decision, Trigger, Condition


class Strategy(Protocol):
    def evaluate(self, ms: MarketState) -> list[Decision]: ...
    def armed_triggers(self, ms: MarketState) -> list[Trigger]: ...
    def conditions(self, ms: MarketState) -> list[Condition]: ...
```

- [ ] **Step 4: Implementar `grid.py`**

```python
from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)


class GridStrategy:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.lower: float | None = None
        self.upper: float | None = None
        self.levels: list[float] = []

    def set_anchor(self, mid: float) -> None:
        self.lower = mid * (1 - self.cfg.grid_range_pct)
        self.upper = mid * (1 + self.cfg.grid_range_pct)
        step = (self.upper - self.lower) / self.cfg.grid_n
        self.levels = [self.lower + step * i for i in range(self.cfg.grid_n + 1)]

    def _rung_size(self, price: float) -> float:
        # Notional por rung; nunca por debajo del minimo de $10.
        notional = max(10.0, self.cfg.capital / (2 * self.cfg.grid_n))
        return notional / price

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        out: list[Trigger] = []
        for lvl in self.levels:
            if lvl < ms.mid:
                out.append(Trigger(ms.coin, lvl, Side.BUY, "place_limit",
                                   f"compra maker en {lvl:.4f}"))
            elif lvl > ms.mid:
                out.append(Trigger(ms.coin, lvl, Side.SELL, "place_limit",
                                   f"venta maker en {lvl:.4f}"))
        return out

    def conditions(self, ms: MarketState) -> list[Condition]:
        in_range = self.lower is not None and self.lower <= ms.mid <= self.upper
        return [Condition("precio_en_rango", ms.mid, self.upper or 0.0, bool(in_range))]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        if self.lower is None or self.upper is None:
            return []
        if ms.mid < self.lower or ms.mid > self.upper:
            return [Decision(ms.coin, ActionType.CLOSE, reduce_only=True,
                             reason="precio fuera de rango (range-exit stop)")]
        out: list[Decision] = []
        for lvl in self.levels:
            if lvl < ms.mid:
                side = Side.BUY
            elif lvl > ms.mid:
                side = Side.SELL
            else:
                continue
            out.append(Decision(ms.coin, ActionType.PLACE_LIMIT, side=side,
                                price=lvl, size=self._rung_size(lvl),
                                reason=f"grid rung {lvl:.4f}"))
        return out
```

- [ ] **Step 5: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_grid.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/strategy/ bot/tests/test_grid.py
git commit -m "feat(bot): interfaz Strategy + GridStrategy"
```

---

### Task 6: `TrendOverlayStrategy`

**Files:**
- Create: `bot/src/hlbot/strategy/trend.py`
- Test: `bot/tests/test_trend.py`

**Interfaces:**
- Consumes: `models`, `indicators` (`ema`, `adx`, `atr`).
- Produces: `TrendOverlayStrategy(cfg)` con `is_trending(ms) -> bool`, `evaluate(ms) -> list[Decision]`, `armed_triggers(ms) -> list[Trigger]`, `conditions(ms) -> list[Condition]`.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_trend.py`

```python
from hlbot.models import MarketState, Candle, RiskLimits, SessionConfig, Side, ActionType
from hlbot.strategy.trend import TrendOverlayStrategy

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits)

def _uptrend_candles(n=60):
    out = []
    for i in range(1, n + 1):
        c = float(i)
        out.append(Candle(t=i, open=c - 0.5, high=c + 0.5, low=c - 0.5, close=c, volume=1.0))
    return out

def _flat_candles(n=60):
    return [Candle(t=i, open=100.0, high=100.5, low=99.5, close=100.0, volume=1.0)
            for i in range(1, n + 1)]

def test_is_trending_true_in_strong_uptrend():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    assert s.is_trending(ms) is True

def test_is_trending_false_when_flat():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=100.0, candles=_flat_candles())
    assert s.is_trending(ms) is False

def test_evaluate_opens_long_with_stop_in_uptrend():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    decisions = s.evaluate(ms)
    actions = [d.action for d in decisions]
    assert ActionType.PLACE_MARKET in actions
    assert ActionType.SET_STOP in actions
    long_d = next(d for d in decisions if d.action == ActionType.PLACE_MARKET)
    assert long_d.side == Side.BUY

def test_conditions_expose_adx():
    s = TrendOverlayStrategy(_cfg())
    ms = MarketState(coin="ETH", mid=60.0, candles=_uptrend_candles())
    names = [c.name for c in s.conditions(ms)]
    assert "adx" in names
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_trend.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.strategy.trend'`)

- [ ] **Step 3: Implementar `trend.py`**

```python
from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)
from hlbot.indicators import ema, adx, atr


class TrendOverlayStrategy:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg

    def _signals(self, ms: MarketState):
        closes = [c.close for c in ms.candles]
        highs = [c.high for c in ms.candles]
        lows = [c.low for c in ms.candles]
        ef = ema(closes, self.cfg.ema_fast)[-1]
        es = ema(closes, self.cfg.ema_slow)[-1]
        adx_ = adx(highs, lows, closes, self.cfg.adx_period)[-1]
        atr_ = atr(highs, lows, closes, self.cfg.atr_period)[-1]
        return ef, es, adx_, atr_

    def is_trending(self, ms: MarketState) -> bool:
        if len(ms.candles) < self.cfg.ema_slow:
            return False
        _, _, adx_, _ = self._signals(ms)
        return adx_ > self.cfg.adx_threshold

    def _size(self, price: float) -> float:
        return max(10.0, self.cfg.capital / 2) / price

    def conditions(self, ms: MarketState) -> list[Condition]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, adx_, _ = self._signals(ms)
        return [
            Condition("adx", adx_, self.cfg.adx_threshold, adx_ > self.cfg.adx_threshold),
            Condition("ema_align", ef - es, 0.0, ef > es),
        ]

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, _, atr_ = self._signals(ms)
        side = Side.SELL if ef >= es else Side.BUY
        stop = ms.mid - self.cfg.atr_stop_mult * atr_ if ef >= es \
            else ms.mid + self.cfg.atr_stop_mult * atr_
        return [Trigger(ms.coin, stop, side, "set_stop",
                        f"trailing stop ATR en {stop:.4f}")]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        if not self.is_trending(ms):
            return []
        ef, es, _, atr_ = self._signals(ms)
        if ef > es:
            stop = ms.mid - self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.BUY,
                         size=self._size(ms.mid),
                         reason="tendencia alcista (ADX>umbral, EMA fast>slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.SELL, price=stop,
                         reduce_only=True, reason="trailing stop ATR"),
            ]
        if ef < es:
            stop = ms.mid + self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.SELL,
                         size=self._size(ms.mid),
                         reason="tendencia bajista (ADX>umbral, EMA fast<slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.BUY, price=stop,
                         reduce_only=True, reason="trailing stop ATR"),
            ]
        return []
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_trend.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/strategy/trend.py bot/tests/test_trend.py
git commit -m "feat(bot): TrendOverlayStrategy (EMA+ADX+ATR)"
```

---

### Task 7: Gestor de riesgo (`RiskManager`)

**Files:**
- Create: `bot/src/hlbot/risk.py`
- Test: `bot/tests/test_risk.py`

**Interfaces:**
- Consumes: `models` (`RiskLimits`).
- Produces: `RiskManager(limits: RiskLimits)` con `can_open(notional, open_positions, leverage) -> tuple[bool, str]` y `should_pause(daily_pnl, total_pnl) -> tuple[bool, str]`.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_risk.py`

```python
from hlbot.models import RiskLimits
from hlbot.risk import RiskManager

def _rm():
    return RiskManager(RiskLimits(max_position_notional=15.0, max_open_positions=2,
                                  max_leverage=2.0, daily_loss_limit=5.0,
                                  total_loss_limit=20.0))

def test_can_open_ok():
    ok, reason = _rm().can_open(notional=10.0, open_positions=0, leverage=1.0)
    assert ok is True and reason == ""

def test_rejects_oversized_notional():
    ok, reason = _rm().can_open(notional=20.0, open_positions=0, leverage=1.0)
    assert ok is False and "notional" in reason

def test_rejects_too_many_positions():
    ok, _ = _rm().can_open(notional=10.0, open_positions=2, leverage=1.0)
    assert ok is False

def test_rejects_excess_leverage():
    ok, _ = _rm().can_open(notional=10.0, open_positions=0, leverage=3.0)
    assert ok is False

def test_should_pause_on_daily_loss():
    pause, reason = _rm().should_pause(daily_pnl=-6.0, total_pnl=-6.0)
    assert pause is True and "diaria" in reason

def test_no_pause_when_within_limits():
    pause, _ = _rm().should_pause(daily_pnl=-1.0, total_pnl=-1.0)
    assert pause is False
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_risk.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.risk'`)

- [ ] **Step 3: Implementar `risk.py`**

```python
from __future__ import annotations
from hlbot.models import RiskLimits


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def can_open(self, notional: float, open_positions: int,
                 leverage: float) -> tuple[bool, str]:
        if notional > self.limits.max_position_notional:
            return False, "excede max_position_notional"
        if open_positions >= self.limits.max_open_positions:
            return False, "max_open_positions alcanzado"
        if leverage > self.limits.max_leverage:
            return False, "excede max_leverage"
        return True, ""

    def should_pause(self, daily_pnl: float, total_pnl: float) -> tuple[bool, str]:
        if daily_pnl <= -self.limits.daily_loss_limit:
            return True, "limite de perdida diaria alcanzado"
        if total_pnl <= -self.limits.total_loss_limit:
            return True, "limite de perdida total alcanzado"
        return False, ""
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_risk.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/risk.py bot/tests/test_risk.py
git commit -m "feat(bot): RiskManager (limites de exposicion y perdida)"
```

---

### Task 8: `HLClient` (envoltorio del SDK + helpers de precisión)

**Files:**
- Create: `bot/src/hlbot/hl_client.py`
- Test: `bot/tests/test_precision.py` (unitario, sin red)
- Test: `bot/tests/test_hl_client_testnet.py` (integración, se salta sin credenciales)

**Interfaces:**
- Consumes: `config` (`Config`), `models`, SDK `hyperliquid.info.Info`, `hyperliquid.exchange.Exchange`, `hyperliquid.utils.constants`, `eth_account.Account`.
- Produces: funciones puras `round_size(size, sz_decimals) -> float`, `round_price(price, sz_decimals, max_decimals=6) -> float`, `meets_min_notional(price, size, min_notional=10.0) -> bool`. Clase `HLClient(cfg)` con `mid(coin) -> float`, `candles(coin, interval, start, end) -> list[dict]`, `user_state() -> dict`, `place_limit(coin, is_buy, price, size, post_only=True, reduce_only=False) -> dict`, `market_close(coin) -> dict`, `cancel_all(coin) -> None`.

> **Verificación del SDK:** los nombres de método del SDK usados abajo (`info.all_mids()`, `info.candles_snapshot(...)`, `info.user_state(addr)`, `info.meta()`, `exchange.order(...)`, `exchange.market_close(...)`, `exchange.cancel(...)`) deben confirmarse contra la versión instalada del `hyperliquid-python-sdk` en el Step 6. Si alguna firma difiere, ajustar la llamada manteniendo la interfaz pública de `HLClient`. El test de integración en testnet es la validación final.

- [ ] **Step 1: Escribir el test de precisión que falla** en `bot/tests/test_precision.py`

```python
from hlbot.hl_client import round_size, round_price, meets_min_notional

def test_round_size_to_decimals():
    assert round_size(0.123456, 3) == 0.123

def test_round_price_decimals_limit():
    # perp con szDecimals=1 -> max 6-1=5 decimales
    assert round_price(1234.567891, sz_decimals=1) == 1234.6  # 5 sig figs

def test_round_price_five_sig_figs():
    assert round_price(0.123456, sz_decimals=2) == 0.12346

def test_min_notional_above_threshold_is_true():
    assert meets_min_notional(3000.0, 0.004) is True   # 12.0 >= 10

def test_min_notional_below_threshold_is_false():
    assert meets_min_notional(3000.0, 0.003) is False  # 9.0 < 10
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_precision.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.hl_client'`)

- [ ] **Step 3: Implementar los helpers puros en `hl_client.py`**

```python
from __future__ import annotations
from hlbot.config import Config


def round_size(size: float, sz_decimals: int) -> float:
    return round(size, sz_decimals)


def round_price(price: float, sz_decimals: int, max_decimals: int = 6) -> float:
    # Hyperliquid perps: max 5 cifras significativas y max (max_decimals - sz_decimals) decimales.
    if price == 0:
        return 0.0
    max_dec = max_decimals - sz_decimals
    # 5 cifras significativas
    from decimal import Decimal
    d = Decimal(repr(price))
    sig = d.adjusted()  # exponente de la cifra mas significativa
    places_for_sig = 4 - sig  # 5 sig figs -> 4 decimales tras la primera cifra
    decimals = min(max_dec, max(0, places_for_sig))
    return round(price, decimals)


def meets_min_notional(price: float, size: float, min_notional: float = 10.0) -> bool:
    return price * size >= min_notional
```

- [ ] **Step 4: Ejecutar tests de precisión y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_precision.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Implementar la clase `HLClient`** (añadir a `hl_client.py`)

```python
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account


class HLClient:
    def __init__(self, cfg: Config):
        base = constants.TESTNET_API_URL if cfg.testnet else constants.MAINNET_API_URL
        self.cfg = cfg
        self.address = cfg.account_address
        self.info = Info(base, skip_ws=True)
        meta = self.info.meta()
        self.sz_decimals = {a["name"]: a["szDecimals"] for a in meta["universe"]}
        self.exchange: Exchange | None = None
        if cfg.secret_key:
            wallet = Account.from_key(cfg.secret_key)
            self.exchange = Exchange(wallet, base, account_address=cfg.account_address)

    def mid(self, coin: str) -> float:
        return float(self.info.all_mids()[coin])

    def candles(self, coin: str, interval: str, start: int, end: int) -> list[dict]:
        return self.info.candles_snapshot(coin, interval, start, end)

    def user_state(self) -> dict:
        return self.info.user_state(self.address)

    def place_limit(self, coin: str, is_buy: bool, price: float, size: float,
                    post_only: bool = True, reduce_only: bool = False) -> dict:
        szd = self.sz_decimals[coin]
        px = round_price(price, szd)
        sz = round_size(size, szd)
        if not reduce_only and not meets_min_notional(px, sz):
            raise ValueError(f"orden por debajo del minimo de $10: {px}*{sz}")
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        tif = "Alo" if post_only else "Gtc"
        return self.exchange.order(coin, is_buy, sz, px, {"limit": {"tif": tif}},
                                   reduce_only=reduce_only)

    def market_close(self, coin: str) -> dict:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        return self.exchange.market_close(coin)

    def cancel_all(self, coin: str) -> None:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        for o in self.info.open_orders(self.address):
            if o["coin"] == coin:
                self.exchange.cancel(coin, o["oid"])
```

- [ ] **Step 6: Escribir el test de integración testnet** en `bot/tests/test_hl_client_testnet.py`

```python
import os
import pytest
from hlbot.config import Config
from hlbot.hl_client import HLClient

pytestmark = pytest.mark.skipif(
    not os.getenv("HL_ACCOUNT_ADDRESS"),
    reason="requiere credenciales testnet en el entorno",
)

def test_mid_and_meta_load_from_testnet():
    cfg = Config.from_env()
    assert cfg.testnet is True  # nunca correr integracion contra mainnet por accidente
    client = HLClient(cfg)
    assert "ETH" in client.sz_decimals
    assert client.mid("ETH") > 0

def test_user_state_returns_account():
    client = HLClient(Config.from_env())
    state = client.user_state()
    assert "marginSummary" in state
```

- [ ] **Step 7: Ejecutar tests (integración se salta sin credenciales)**

Run: `cd bot && python -m pytest tests/test_precision.py tests/test_hl_client_testnet.py -v`
Expected: precision PASS (5); integración SKIPPED (sin credenciales) o PASS (con credenciales testnet en `.env`). Si pasan con credenciales, confirma que los nombres de método del SDK son correctos; si fallan por firma, ajustar según la nota de "Verificación del SDK".

- [ ] **Step 8: Commit**

```bash
git add bot/src/hlbot/hl_client.py bot/tests/test_precision.py bot/tests/test_hl_client_testnet.py
git commit -m "feat(bot): HLClient (envoltorio SDK + precision + min notional)"
```

---

### Task 9: `SessionEngine` (máquina de estados)

**Files:**
- Create: `bot/src/hlbot/session_engine.py`
- Test: `bot/tests/test_session_engine.py`

**Interfaces:**
- Consumes: `models`, `strategy.grid.GridStrategy`, `strategy.trend.TrendOverlayStrategy`, `risk.RiskManager`, `store.Store`; un cliente con interfaz `mid(coin)`, `user_state()`, `place_limit(...)`, `market_close(coin)`, `cancel_all(coin)`, `candles(...)` (inyectado; en tests un `FakeClient`).
- Produces: `SessionEngine(client, store)` con atributos `state: SessionState`, `paused: bool` y métodos `launch(cfg: SessionConfig)`, `close()`, `kill(confirm: bool)`, `tick(market_states: dict[str, MarketState])`, `snapshot() -> dict` (estado serializable: state, paused, watchlist, triggers, conditions por coin).

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_session_engine.py`

```python
import pytest
from hlbot.models import (
    MarketState, Candle, RiskLimits, SessionConfig, SessionState, ActionType,
)
from hlbot.session_engine import SessionEngine

class FakeClient:
    def __init__(self):
        self.orders = []
        self.closed = []
        self._mid = {"ETH": 3000.0}
    def mid(self, coin): return self._mid[coin]
    def user_state(self): return {"assetPositions": [], "marginSummary": {"accountValue": "40"}}
    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        self.orders.append((coin, is_buy, price, size, reduce_only)); return {"status": "ok"}
    def market_close(self, coin): self.closed.append(coin); return {"status": "ok"}
    def cancel_all(self, coin): pass

class FakeStore:
    def __init__(self): self.decisions = []; self.sid = 1
    def create_session(self, watchlist, capital): return self.sid
    def end_session(self, sid): pass
    def record_decision(self, sid, coin, action, reason): self.decisions.append((coin, action, reason))
    def record_risk_event(self, sid, kind, detail): pass
    def record_pnl_snapshot(self, sid, pnl): pass

def _cfg():
    limits = RiskLimits(15.0, 3, 2.0, 5.0, 20.0)
    return SessionConfig(watchlist=["ETH"], capital=40.0, limits=limits,
                         grid_n=4, grid_range_pct=0.02)

def _flat_ms():
    candles = [Candle(t=i, open=3000, high=3001, low=2999, close=3000, volume=1.0)
               for i in range(1, 60)]
    return {"ETH": MarketState(coin="ETH", mid=3000.0, candles=candles)}

def test_launch_moves_to_scanning():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    assert eng.state == SessionState.SCANNING

def test_launch_rejected_when_not_idle():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    with pytest.raises(RuntimeError):
        eng.launch(_cfg())

def test_tick_places_grid_orders_when_flat():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    assert len(client.orders) > 0

def test_close_blocks_new_orders():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.close()
    assert eng.state == SessionState.CLOSING
    eng.tick(_flat_ms())
    # en CLOSING no se abren nuevas (no reduce_only)
    assert all(o[4] is True for o in client.orders) or client.orders == []

def test_kill_requires_confirmation_and_closes_all():
    client = FakeClient()
    eng = SessionEngine(client, FakeStore())
    eng.launch(_cfg())
    eng.tick(_flat_ms())
    with pytest.raises(ValueError):
        eng.kill(confirm=False)
    eng.kill(confirm=True)
    assert eng.state == SessionState.IDLE
    assert "ETH" in client.closed

def test_snapshot_exposes_triggers_and_conditions():
    eng = SessionEngine(FakeClient(), FakeStore())
    eng.launch(_cfg())
    snap = eng.snapshot(_flat_ms())
    assert snap["state"] == "scanning"
    assert "ETH" in snap["coins"]
    assert "triggers" in snap["coins"]["ETH"]
    assert "conditions" in snap["coins"]["ETH"]
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_session_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.session_engine'`)

- [ ] **Step 3: Implementar `session_engine.py`**

```python
from __future__ import annotations
from hlbot.models import (
    MarketState, SessionState, SessionConfig, ActionType, Side, to_dict,
)
from hlbot.strategy.grid import GridStrategy
from hlbot.strategy.trend import TrendOverlayStrategy
from hlbot.risk import RiskManager


class SessionEngine:
    def __init__(self, client, store):
        self.client = client
        self.store = store
        self.state = SessionState.IDLE
        self.paused = False
        self.cfg: SessionConfig | None = None
        self.session_id: int | None = None
        self.risk: RiskManager | None = None
        self.grids: dict[str, GridStrategy] = {}
        self.trends: dict[str, TrendOverlayStrategy] = {}

    def launch(self, cfg: SessionConfig) -> None:
        if self.state != SessionState.IDLE:
            raise RuntimeError(f"no se puede lanzar en estado {self.state}")
        self.cfg = cfg
        self.risk = RiskManager(cfg.limits)
        self.session_id = self.store.create_session(cfg.watchlist, cfg.capital)
        self.grids = {}
        self.trends = {}
        for coin in cfg.watchlist:
            g = GridStrategy(cfg)
            g.set_anchor(self.client.mid(coin))
            self.grids[coin] = g
            self.trends[coin] = TrendOverlayStrategy(cfg)
        self.paused = False
        self.state = SessionState.SCANNING

    def close(self) -> None:
        if self.state in (SessionState.SCANNING, SessionState.ACTIVE):
            self.state = SessionState.CLOSING

    def kill(self, confirm: bool) -> None:
        if not confirm:
            raise ValueError("kill requiere confirmacion explicita")
        if self.cfg:
            for coin in self.cfg.watchlist:
                self.client.cancel_all(coin)
                self.client.market_close(coin)
        if self.session_id is not None:
            self.store.end_session(self.session_id)
        self._reset()

    def _reset(self) -> None:
        self.state = SessionState.IDLE
        self.paused = False
        self.cfg = None
        self.session_id = None
        self.risk = None
        self.grids = {}
        self.trends = {}

    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if trend.is_trending(ms):
            return trend.evaluate(ms)  # tendencia: pausa el grid de este par
        return grid.evaluate(ms)

    def _open_positions_count(self) -> int:
        state = self.client.user_state()
        return len(state.get("assetPositions", []))

    def tick(self, market_states: dict[str, MarketState]) -> None:
        if self.state == SessionState.IDLE or self.cfg is None:
            return
        for coin, ms in market_states.items():
            if coin not in self.grids:
                continue
            decisions = self._decisions_for(ms)
            for d in decisions:
                # En CLOSING solo se permiten ordenes reduce_only / cierres.
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                self._apply(coin, ms, d)
        if self.state == SessionState.CLOSING and self._open_positions_count() == 0:
            self._reset()

    def _apply(self, coin: str, ms: MarketState, d) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            notional = (d.price or 0) * (d.size or 0)
            ok, reason = self.risk.can_open(notional, self._open_positions_count(),
                                            self.cfg.limits.max_leverage)
            if not ok:
                self.store.record_risk_event(self.session_id, "rechazo", reason)
                return
            self.client.place_limit(coin, d.side == Side.BUY, d.price, d.size,
                                    post_only=True, reduce_only=d.reduce_only)
            self.state = SessionState.ACTIVE
        elif d.action == ActionType.PLACE_MARKET:
            notional = ms.mid * (d.size or 0)
            ok, reason = self.risk.can_open(notional, self._open_positions_count(),
                                            self.cfg.limits.max_leverage)
            if not ok:
                self.store.record_risk_event(self.session_id, "rechazo", reason)
                return
            self.client.place_limit(coin, d.side == Side.BUY, ms.mid, d.size,
                                    post_only=False, reduce_only=d.reduce_only)
            self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            self.client.market_close(coin)
        # SET_STOP se registra como decision; el motor lo gestionara en una iteracion futura.
        self.store.record_decision(self.session_id, coin, d.action.value, d.reason)

    def snapshot(self, market_states: dict[str, MarketState] | None = None) -> dict:
        coins: dict[str, dict] = {}
        if self.cfg and market_states:
            for coin, ms in market_states.items():
                if coin not in self.grids:
                    continue
                grid = self.grids[coin]
                trend = self.trends[coin]
                trending = trend.is_trending(ms)
                active = trend if trending else grid
                coins[coin] = {
                    "mid": ms.mid,
                    "mode": "trend" if trending else "grid",
                    "triggers": [to_dict(t) for t in active.armed_triggers(ms)],
                    "conditions": [to_dict(c) for c in active.conditions(ms)],
                }
        return {
            "state": self.state.value,
            "paused": self.paused,
            "watchlist": self.cfg.watchlist if self.cfg else [],
            "coins": coins,
        }
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_session_engine.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/src/hlbot/session_engine.py bot/tests/test_session_engine.py
git commit -m "feat(bot): SessionEngine (maquina de estados launch/close/kill/tick)"
```

---

### Task 10: API FastAPI (REST + WebSocket)

**Files:**
- Create: `bot/src/hlbot/api.py`
- Test: `bot/tests/test_api.py`

**Interfaces:**
- Consumes: `config.Config`, `session_engine.SessionEngine`, `models` (`SessionConfig`, `RiskLimits`).
- Produces: `create_app(engine, control_token, market_state_provider) -> FastAPI`. Rutas: `GET /state`, `GET /history` (decisiones de la sesión actual), `POST /session/launch`, `POST /session/close`, `POST /session/kill`, `POST /limits`, `WS /ws`. Las rutas de control exigen cabecera `X-Control-Token`.

> `market_state_provider() -> dict[str, MarketState]` es una función inyectada que construye los `MarketState` actuales (en producción la implementa el bucle del motor con `HLClient`; en tests, un stub). Mantiene la API desacoplada de la red.

- [ ] **Step 1: Escribir el test que falla** en `bot/tests/test_api.py`

```python
from fastapi.testclient import TestClient
from hlbot.api import create_app
from hlbot.models import MarketState, Candle
from hlbot.session_engine import SessionEngine
from test_session_engine import FakeClient, FakeStore  # pytest expone el modulo por nombre simple

TOKEN = "secret-tok"

def _provider():
    candles = [Candle(t=i, open=3000, high=3001, low=2999, close=3000, volume=1.0)
               for i in range(1, 60)]
    return {"ETH": MarketState(coin="ETH", mid=3000.0, candles=candles)}

def _client():
    engine = SessionEngine(FakeClient(), FakeStore())
    app = create_app(engine, TOKEN, _provider)
    return TestClient(app), engine

def test_state_is_idle_initially():
    client, _ = _client()
    r = client.get("/state")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"

def test_launch_requires_token():
    client, _ = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body)
    assert r.status_code == 401

def test_launch_with_token_moves_to_scanning():
    client, engine = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    r = client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    assert r.status_code == 200
    assert engine.state.value == "scanning"

def test_kill_requires_confirm_flag():
    client, engine = _client()
    body = {"watchlist": ["ETH"], "capital": 40.0,
            "limits": {"max_position_notional": 15.0, "max_open_positions": 3,
                       "max_leverage": 2.0, "daily_loss_limit": 5.0,
                       "total_loss_limit": 20.0}}
    client.post("/session/launch", json=body, headers={"X-Control-Token": TOKEN})
    r = client.post("/session/kill", json={"confirm": False},
                    headers={"X-Control-Token": TOKEN})
    assert r.status_code == 400
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd bot && python -m pytest tests/test_api.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'hlbot.api'`)

- [ ] **Step 3: Implementar `api.py`**

```python
from __future__ import annotations
import asyncio
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from hlbot.models import SessionConfig, RiskLimits
from hlbot.session_engine import SessionEngine


class LimitsBody(BaseModel):
    max_position_notional: float
    max_open_positions: int
    max_leverage: float
    daily_loss_limit: float
    total_loss_limit: float


class LaunchBody(BaseModel):
    watchlist: list[str]
    capital: float
    limits: LimitsBody
    grid_n: int = 10
    grid_range_pct: float = 0.03
    adx_threshold: float = 25.0


class KillBody(BaseModel):
    confirm: bool


def create_app(engine: SessionEngine, control_token: str,
               market_state_provider) -> FastAPI:
    app = FastAPI(title="hlbot")

    def _auth(token: str | None):
        if token != control_token:
            raise HTTPException(status_code=401, detail="token de control invalido")

    @app.get("/state")
    def state():
        return engine.snapshot(market_state_provider())

    @app.get("/history")
    def history():
        if engine.session_id is None:
            return {"decisions": []}
        return {"decisions": engine.store.get_decisions(engine.session_id)}

    @app.post("/session/launch")
    def launch(body: LaunchBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        limits = RiskLimits(**body.limits.model_dump())
        cfg = SessionConfig(watchlist=body.watchlist, capital=body.capital,
                            limits=limits, grid_n=body.grid_n,
                            grid_range_pct=body.grid_range_pct,
                            adx_threshold=body.adx_threshold)
        try:
            engine.launch(cfg)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"state": engine.state.value}

    @app.post("/session/close")
    def close(x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        engine.close()
        return {"state": engine.state.value}

    @app.post("/session/kill")
    def kill(body: KillBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        try:
            engine.kill(confirm=body.confirm)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"state": engine.state.value}

    @app.post("/limits")
    def update_limits(body: LimitsBody, x_control_token: str | None = Header(default=None)):
        _auth(x_control_token)
        if engine.risk is None:
            raise HTTPException(status_code=409, detail="no hay sesion activa")
        engine.risk.limits = RiskLimits(**body.model_dump())
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(engine.snapshot(market_state_provider()))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

    return app
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd bot && python -m pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Ejecutar toda la suite**

Run: `cd bot && python -m pytest -v`
Expected: todos PASS (integración testnet SKIPPED sin credenciales).

- [ ] **Step 6: Commit**

```bash
git add bot/src/hlbot/api.py bot/tests/test_api.py
git commit -m "feat(bot): API FastAPI (REST + WebSocket) con token de control"
```

---

## Notas para el ejecutor

- **Orden de ejecución:** las tareas están en orden de dependencia; ejecútalas en secuencia.
- **El bucle vivo del motor** (un proceso que llama a `engine.tick()` periódicamente con `MarketState` reales construidos vía `HLClient` + `candles()` + `mid()`, y arranca `uvicorn`) se ensambla como un pequeño `main.py` al final del sub-proyecto; su `market_state_provider` alimenta tanto el tick como la API. Esa orquestación final y el servicio launchd se detallan al cerrar el sub-proyecto 1, una vez todos los componentes pasan sus tests.
- **Grabación de velas** (`market_candles`) para backtests profundos: el bucle vivo persiste cada vela nueva que ve; el backtester (sub-proyecto 3) la consumirá.
- **Validación en testnet:** rellena `.env` con la API wallet de testnet (faucet en `app.hyperliquid-testnet.xyz/drip`) y ejecuta la suite completa con credenciales para validar `HLClient` de extremo a extremo antes de pasar al dashboard.
