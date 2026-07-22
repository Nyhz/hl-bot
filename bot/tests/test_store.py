import threading

import hlbot.store as store_mod
from hlbot.store import Store

def test_reuses_single_connection_no_fd_leak(tmp_path, monkeypatch):
    # Regresión: cada operación abría una conexión sqlite nueva y nunca la
    # cerraba (el `with conn` solo hace commit, no close) -> fuga de FDs que
    # acababa en "unable to open database file" al llegar al límite del proceso.
    real_connect = store_mod.sqlite3.connect
    opened = []

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(store_mod.sqlite3, "connect", tracking_connect)

    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    for i in range(50):
        store.record_pnl_snapshot(sid, float(i))
        store.get_pnl_snapshots(sid)

    assert len(opened) == 1, (
        f"se abrieron {len(opened)} conexiones; debe reutilizar una sola"
    )

def test_concurrent_access_from_threads(tmp_path):
    # La conexión única se comparte entre hilos (tick va en asyncio.to_thread
    # + la API): debe ser segura, sin "objects created in a thread..." ni
    # corrupción.
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 40.0)
    errors: list[Exception] = []

    def worker(n: int):
        try:
            for i in range(20):
                store.record_pnl_snapshot(sid, float(n * 100 + i))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(store.get_pnl_snapshots(sid)) == 80

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


def test_save_runtime_upserts_single_row(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    store.save_runtime(sid, '{"v": 1}')
    store.save_runtime(sid, '{"v": 2}')                    # upsert, no acumula filas
    rows = store.open_sessions("testnet")
    assert len(rows) == 1
    assert rows[0]["payload"] == '{"v": 2}'


def test_open_sessions_filters_mode_and_ended(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    s_test = store.create_session(["ETH"], 40.0, mode="testnet")
    s_main = store.create_session(["BTC"], 40.0, mode="mainnet")
    s_done = store.create_session(["SOL"], 40.0, mode="testnet")
    store.end_session(s_done)
    rows = store.open_sessions("testnet")
    assert [r["id"] for r in rows] == [s_test]             # ni mainnet ni acabadas
    assert rows[0]["payload"] is None                      # sin runtime guardado


def test_open_sessions_newest_first(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    old = store.create_session(["ETH"], 40.0, mode="testnet")
    new = store.create_session(["ETH"], 40.0, mode="testnet")
    rows = store.open_sessions("testnet")
    assert [r["id"] for r in rows] == [new, old]


def test_session_config_json_roundtrip(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    store.set_session_config(sid, '{"grid_n": 4}')
    assert store.get_session(sid)["config_json"] == '{"grid_n": 4}'


def test_micro_batch_roundtrip(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    store.record_micro_batch(sid, [
        {"ts": 100, "coin": "ETH", "mid": 3000.0, "microprice": 3001.0,
         "sigma_px": 2.0, "flow_ratio": 0.3, "inventory": 0.004, "toxic": 0},
        {"ts": 100, "coin": "BTC", "mid": 61000.0, "toxic": 1},
    ])
    rows = store.get_micro(sid)
    assert len(rows) == 2
    eth = store.get_micro(sid, coin="ETH")
    assert len(eth) == 1 and eth[0]["microprice"] == 3001.0
    assert eth[0]["best_bid"] is None                     # columnas ausentes -> NULL
    assert store.get_micro(sid, coin="BTC")[0]["toxic"] == 1
    store.record_micro_batch(sid, [])                     # batch vacío: no-op


def test_pnl_snapshot_rich_columns(tmp_path):
    store = Store(str(tmp_path / "t.db")); store.init_schema()
    sid = store.create_session(["ETH"], 40.0, mode="testnet")
    store.record_pnl_snapshot(sid, 40.5, unrealized=0.5, gross=12.0,
                              net_delta=-12.0, open_count=1, l1_total=77)
    with store._conn() as conn:
        row = dict(conn.execute("SELECT * FROM pnl_snapshots WHERE session_id=?",
                                (sid,)).fetchone())
    assert row["total_pnl"] == 40.5 and row["unrealized"] == 0.5
    assert row["net_delta"] == -12.0 and row["l1_total"] == 77
    # el getter de la curva de equity sigue funcionando igual
    assert store.get_pnl_snapshots(sid)[0]["total_pnl"] == 40.5


def test_record_extras_parses_and_dedups(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 60.0)
    fills = [
        {"tid": 111, "time": 1_784_000_000_000, "coin": "ETH", "side": "A",
         "dir": "Close Long", "px": "3000.5", "sz": "0.01", "fee": "0.0015",
         "closedPnl": "-0.5"},
        {"hash": "0xabc", "time": 1_784_000_001_000, "coin": "BTC", "side": "B",
         "dir": "Open Long", "px": 60000.0, "sz": 0.0002, "fee": 0.0018},
        {"time": 1_784_000_002_000, "coin": "ETH"},   # sin tid ni hash: se ignora
    ]
    ZERO_HASH = "0x" + "0" * 64                        # HL: hash nulo en funding
    funding = [{"time": 1_784_000_000_000, "hash": ZERO_HASH,
                "delta": {"coin": "ETH", "usdc": "-0.01"}},
               {"time": 1_784_003_600_000, "hash": ZERO_HASH,
                "delta": {"coin": "ETH", "usdc": "0.02"}}]
    store.record_extras(sid, fills, funding)
    store.record_extras(sid, fills, funding)           # segunda pasada: dedup total
    got = store.get_fills(sid)
    assert len(got) == 2
    eth = next(f for f in got if f["coin"] == "ETH")
    assert eth["closed_pnl"] == -0.5 and eth["price"] == 3000.5
    # dos horas de funding con el mismo hash nulo: AMBAS grabadas, sin colisión
    assert len(store.get_funding(sid)) == 2


def test_recent_markout_windowed_mean(tmp_path):
    import time as _t
    store = Store(str(tmp_path / "t.db"))
    store.init_schema()
    sid = store.create_session(["ETH"], 60.0)
    now = int(_t.time())
    # 2 fills dentro de la ventana, 1 fuera, 1 dentro pero sin markout aún
    store.record_fill_unique(sid, "a", now - 100, "ETH", "B", "Open Long", 3000, 0.01, 0.001, 0)
    store.record_fill_unique(sid, "b", now - 200, "ETH", "A", "Close Long", 3001, 0.01, 0.001, 0.1)
    store.record_fill_unique(sid, "c", now - 9000, "ETH", "B", "Open Long", 2990, 0.01, 0.001, 0)
    store.record_fill_unique(sid, "d", now - 50, "ETH", "B", "Open Long", 3002, 0.01, 0.001, 0)
    for f in store.fills_missing_markout(sid, 30, now + 1000, 100000):
        if f["ts"] != now - 50:                      # "d" queda sin markout
            store.set_fill_markout(f["id"], 30, 4.0 if f["ts"] >= now - 300 else -9.0)
    n, mean = store.recent_markout(sid, now - 7200)
    assert n == 2 and mean == 4.0                    # "c" fuera de ventana, "d" NULL
    n_all, _ = store.recent_markout(sid, 0)
    assert n_all == 3
