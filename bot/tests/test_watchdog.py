import pytest
from hlbot.watchdog import check_once, heartbeat_age, STALE_SECONDS

NOW = 1_000_000.0


class _FakeInfo:
    def __init__(self, orders):
        self._orders = orders

    def open_orders(self, addr):
        return self._orders


class _FakeClient:
    def __init__(self, orders):
        self.info = _FakeInfo(orders)
        self.address = "0xabc"
        self.canceled = []

    def cancel_order(self, coin, oid):
        self.canceled.append((coin, oid))


def _paths(tmp_path):
    return str(tmp_path / "heartbeat"), str(tmp_path / "latch")


def _write_hb(path, ts):
    with open(path, "w") as f:
        f.write(str(ts))


def test_fresh_heartbeat_no_action(tmp_path):
    hb, latch = _paths(tmp_path)
    _write_hb(hb, NOW - 10)

    def _boom():
        raise AssertionError("no debe construir el cliente con latido fresco")
    msgs = []
    assert check_once(_boom, NOW, hb, latch, notifier=msgs.append) == "ok"
    assert msgs == []


def test_stale_cancels_resting_and_latches(tmp_path):
    hb, latch = _paths(tmp_path)
    _write_hb(hb, NOW - STALE_SECONDS - 60)
    client = _FakeClient([{"coin": "ETH", "oid": 1}, {"coin": "BTC", "oid": 2}])
    msgs = []
    assert check_once(lambda: client, NOW, hb, latch, notifier=msgs.append) == "acted"
    assert client.canceled == [("ETH", 1), ("BTC", 2)]
    assert msgs and "sin latido" in msgs[0]
    import os
    assert os.path.exists(latch)                       # no repetirá la acción


def test_latched_does_not_repeat(tmp_path):
    hb, latch = _paths(tmp_path)
    _write_hb(hb, NOW - STALE_SECONDS - 60)
    client = _FakeClient([{"coin": "ETH", "oid": 1}])
    check_once(lambda: client, NOW, hb, latch, notifier=lambda m: None)
    assert check_once(lambda: client, NOW + 60, hb, latch,
                      notifier=lambda m: None) == "latched"
    assert len(client.canceled) == 1                   # no volvió a cancelar


def test_recovery_clears_latch_and_notifies(tmp_path):
    hb, latch = _paths(tmp_path)
    _write_hb(hb, NOW - STALE_SECONDS - 60)
    check_once(lambda: _FakeClient([]), NOW, hb, latch, notifier=lambda m: None)
    _write_hb(hb, NOW + 120)                           # el bot volvió a latir
    msgs = []
    assert check_once(lambda: _FakeClient([]), NOW + 125, hb, latch,
                      notifier=msgs.append) == "ok"
    import os
    assert not os.path.exists(latch)
    assert msgs and "recuperado" in msgs[0]


def test_missing_heartbeat_is_stale(tmp_path):
    # bot que nunca arrancó (o fichero borrado): tratarlo como caído, no como sano
    hb, latch = _paths(tmp_path)
    client = _FakeClient([{"coin": "ETH", "oid": 9}])
    assert check_once(lambda: client, NOW, hb, latch,
                      notifier=lambda m: None) == "acted"
    assert client.canceled == [("ETH", 9)]
    assert heartbeat_age(NOW, hb) == float("inf")


def test_cancel_error_does_not_abort_the_rest(tmp_path):
    hb, latch = _paths(tmp_path)

    class _Flaky(_FakeClient):
        def cancel_order(self, coin, oid):
            if oid == 1:
                raise RuntimeError("red caída a mitad")
            super().cancel_order(coin, oid)

    client = _Flaky([{"coin": "ETH", "oid": 1}, {"coin": "BTC", "oid": 2}])
    msgs = []
    assert check_once(lambda: client, NOW, hb, latch, notifier=msgs.append) == "acted"
    assert client.canceled == [("BTC", 2)]             # siguió con las demás
    assert "1/2" in msgs[0]
