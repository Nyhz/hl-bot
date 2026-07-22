from __future__ import annotations
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    watchlist TEXT NOT NULL,
    capital REAL NOT NULL,
    ended_at INTEGER,
    mode TEXT
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
    fee REAL NOT NULL,
    tid TEXT,
    closed_pnl REAL,
    dir TEXT
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
    amount REAL NOT NULL,
    fkey TEXT
);
CREATE TABLE IF NOT EXISTS market_candles (
    coin TEXT NOT NULL,
    interval TEXT NOT NULL,
    t INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (coin, interval, t)
);
CREATE TABLE IF NOT EXISTS micro_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    coin TEXT NOT NULL,
    mid REAL, best_bid REAL, best_ask REAL, bid_sz REAL, ask_sz REAL,
    microprice REAL, sigma_px REAL, flow_usd REAL, flow_total_usd REAL,
    flow_ratio REAL, funding REAL, inventory REAL, toxic INTEGER
);
CREATE INDEX IF NOT EXISTS idx_micro_session_ts
    ON micro_snapshots(session_id, ts);
CREATE TABLE IF NOT EXISTS session_runtime (
    session_id INTEGER PRIMARY KEY,
    updated_at INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""

MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN mode TEXT",
    "ALTER TABLE fills ADD COLUMN tid TEXT",
    "ALTER TABLE fills ADD COLUMN closed_pnl REAL",
    "ALTER TABLE fills ADD COLUMN dir TEXT",
    "ALTER TABLE funding_payments ADD COLUMN fkey TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_tid ON fills(tid)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_funding_fkey ON funding_payments(fkey)",
    # Markouts por fill (bps a +5s/+30s/+120s; NULL = pendiente o sin histórico)
    "ALTER TABLE fills ADD COLUMN markout_5s REAL",
    "ALTER TABLE fills ADD COLUMN markout_30s REAL",
    "ALTER TABLE fills ADD COLUMN markout_120s REAL",
    # Config completa e inmutable de lanzamiento (sessions solo tenía watchlist+capital)
    "ALTER TABLE sessions ADD COLUMN config_json TEXT",
    # Series de exposición/churn junto a la equity (análisis de test runs)
    "ALTER TABLE pnl_snapshots ADD COLUMN unrealized REAL",
    "ALTER TABLE pnl_snapshots ADD COLUMN gross REAL",
    "ALTER TABLE pnl_snapshots ADD COLUMN net_delta REAL",
    "ALTER TABLE pnl_snapshots ADD COLUMN open_count INTEGER",
    "ALTER TABLE pnl_snapshots ADD COLUMN l1_total INTEGER",
]


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Una sola conexión persistente para todo el proceso. Antes se abría
        # una por operación y nunca se cerraba (el `with conn` solo hace
        # commit/rollback, no close), fugando descriptores hasta agotar el
        # límite del proceso -> "unable to open database file".
        # check_same_thread=False porque el tick va en asyncio.to_thread y la
        # API la usa desde otros hilos; el lock serializa los accesos.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._db
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            for stmt in MIGRATIONS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # columna/índice ya existe (BD antigua o nueva)

    def create_session(self, watchlist: list[str], capital: float,
                       mode: str = "testnet") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, watchlist, capital, mode) "
                "VALUES (?, ?, ?, ?)",
                (int(time.time()), ",".join(watchlist), capital, mode),
            )
            return int(cur.lastrowid)

    def list_sessions(self, mode: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if mode is not None:
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

    def record_pnl_snapshot(self, session_id: int, total_pnl: float,
                            unrealized: float | None = None,
                            gross: float | None = None,
                            net_delta: float | None = None,
                            open_count: int | None = None,
                            l1_total: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pnl_snapshots (session_id, ts, total_pnl, unrealized, "
                "gross, net_delta, open_count, l1_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, int(time.time()), total_pnl, unrealized,
                 gross, net_delta, open_count, l1_total),
            )

    def set_session_config(self, session_id: int, config_json: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET config_json=? WHERE id=?",
                         (config_json, session_id))

    MICRO_COLS = ("ts", "coin", "mid", "best_bid", "best_ask", "bid_sz", "ask_sz",
                  "microprice", "sigma_px", "flow_usd", "flow_total_usd",
                  "flow_ratio", "funding", "inventory", "toxic")

    def record_micro_batch(self, session_id: int, rows: list[dict]) -> None:
        # Serie de microestructura por tick y moneda: lo que hace analizable un
        # test run a posteriori (reserva A-S reconstruible, contexto de cada fill).
        if not rows:
            return
        cols = ", ".join(self.MICRO_COLS)
        ph = ", ".join("?" * (len(self.MICRO_COLS) + 1))
        with self._conn() as conn:
            conn.executemany(
                f"INSERT INTO micro_snapshots (session_id, {cols}) VALUES ({ph})",
                [(session_id, *[r.get(c) for c in self.MICRO_COLS]) for r in rows])

    def get_micro(self, session_id: int, coin: str | None = None,
                  limit: int = 20000) -> list[dict]:
        with self._conn() as conn:
            if coin:
                rows = conn.execute(
                    "SELECT * FROM micro_snapshots WHERE session_id=? AND coin=? "
                    "ORDER BY id DESC LIMIT ?", (session_id, coin, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM micro_snapshots WHERE session_id=? "
                    "ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]

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

    def record_extras(self, session_id: int, fills: list[dict],
                      funding: list[dict]) -> None:
        # Persistencia dedup (por tid/fkey) de los payloads crudos de
        # user_fills/user_funding de HL. La usan el runner en cada refresco y
        # el engine en la foto final de kill/close.
        for f in fills:
            tid = str(f.get("tid") if f.get("tid") is not None else f.get("hash", ""))
            if not tid:
                continue
            self.record_fill_unique(
                session_id, tid, int(f.get("time", 0) or 0) // 1000, f.get("coin"),
                f.get("side", ""), f.get("dir", ""), float(f.get("px", 0) or 0),
                float(f.get("sz", 0) or 0), float(f.get("fee", 0) or 0),
                float(f.get("closedPnl", 0) or 0))
        for fp in funding:
            delta = fp.get("delta", {}) or {}
            fkey = str(fp.get("hash") or f"{fp.get('time','')}-{delta.get('coin','')}")
            self.record_funding_unique(
                session_id, fkey, int(fp.get("time", 0) or 0) // 1000,
                delta.get("coin", ""), float(delta.get("usdc", 0) or 0))

    def save_runtime(self, session_id: int, payload: str) -> None:
        # Snapshot del estado vivo del engine (1 fila por sesión, upsert por tick):
        # lo que permite rehidratar la sesión tras un reinicio del proceso.
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO session_runtime (session_id, updated_at, payload) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "updated_at=excluded.updated_at, payload=excluded.payload",
                (session_id, int(time.time()), payload),
            )

    def open_sessions(self, mode: str) -> list[dict]:
        # Sesiones sin cerrar del MODO actual (nunca rehidratar testnet en mainnet
        # ni viceversa), la más reciente primero, con su runtime si existe.
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT s.*, r.payload FROM sessions s "
                "LEFT JOIN session_runtime r ON r.session_id = s.id "
                "WHERE s.ended_at IS NULL AND s.mode = ? ORDER BY s.id DESC",
                (mode,)).fetchall()
            return [dict(r) for r in rows]

    MARKOUT_COLS = {5: "markout_5s", 30: "markout_30s", 120: "markout_120s"}

    def recent_markout(self, session_id: int, since_ts: float,
                       horizon_s: int = 30) -> tuple[int, float | None]:
        # Muestra móvil del markout: nº de fills con markout ya calculado
        # desde since_ts y su media en bps (None sin muestra).
        col = self.MARKOUT_COLS[horizon_s]
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT({col}), AVG({col}) FROM fills "
                f"WHERE session_id=? AND ts >= ? AND {col} IS NOT NULL",
                (session_id, int(since_ts))).fetchone()
            return int(row[0] or 0), row[1]

    def fills_missing_markout(self, session_id: int, horizon_s: int,
                              now: float, max_lookback_s: float) -> list[dict]:
        # Fills cuyo horizonte ya venció y siguen sin markout, dentro de la
        # ventana que el histórico de precios en memoria aún cubre.
        col = self.MARKOUT_COLS[horizon_s]
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, coin, side, price, ts FROM fills "
                f"WHERE session_id=? AND {col} IS NULL "
                f"AND ts + ? <= ? AND ts >= ?",
                (session_id, horizon_s, now, now - max_lookback_s)).fetchall()
            return [dict(r) for r in rows]

    def set_fill_markout(self, fill_id: int, horizon_s: int, bps: float) -> None:
        col = self.MARKOUT_COLS[horizon_s]
        with self._conn() as conn:
            conn.execute(f"UPDATE fills SET {col}=? WHERE id=?", (bps, fill_id))

    def markout_summary(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT coin, COUNT(markout_5s) AS n, AVG(markout_5s) AS m5, "
                "AVG(markout_30s) AS m30, AVG(markout_120s) AS m120 "
                "FROM fills WHERE session_id=? AND markout_5s IS NOT NULL "
                "GROUP BY coin", (session_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_funding(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM funding_payments WHERE session_id=? ORDER BY id",
                (session_id,)).fetchall()
            return [dict(r) for r in rows]
