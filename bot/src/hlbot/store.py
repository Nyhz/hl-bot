from __future__ import annotations
import sqlite3
import time

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
]


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

    def get_funding(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM funding_payments WHERE session_id=? ORDER BY id",
                (session_id,)).fetchall()
            return [dict(r) for r in rows]
