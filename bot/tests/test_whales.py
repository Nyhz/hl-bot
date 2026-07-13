from hlbot.whales import WhaleWatch, FILLS_PER_ADDRESS

ADDR = "0xAbC123"


def _ww():
    return WhaleWatch("https://example", [ADDR])   # sin start(): sin red


def _msg(fills, user=ADDR):
    return {"data": {"user": user, "fills": fills}}


def _fill(tid, coin="BTC", side="B", px="61000", sz="0.001", t=1_000_000):
    return {"tid": tid, "coin": coin, "side": side, "px": px, "sz": sz,
            "time": t * 1000, "dir": "Open Long", "closedPnl": "0"}


def test_fills_recorded_newest_first_and_normalized():
    ww = _ww()
    ww._on_fills(_msg([_fill(1, t=100), _fill(2, t=200)]))
    rec = ww.recent()
    tape = rec[ADDR.lower()]
    assert [f["tid"] for f in tape] == ["2", "1"]        # más nuevo primero
    assert tape[0]["coin"] == "BTC" and tape[0]["px"] == 61000.0
    assert tape[0]["ts"] == 200


def test_fills_dedup_by_tid():
    ww = _ww()
    ww._on_fills(_msg([_fill(7)]))
    ww._on_fills(_msg([_fill(7)]))                       # snapshot + update repetido
    assert len(ww.recent()[ADDR.lower()]) == 1


def test_unknown_address_ignored():
    ww = _ww()
    ww._on_fills(_msg([_fill(1)], user="0xOtra"))
    assert ww.recent()[ADDR.lower()] == []


def test_tape_bounded():
    ww = _ww()
    ww._on_fills(_msg([_fill(i) for i in range(FILLS_PER_ADDRESS * 2)]))
    assert len(ww.recent()[ADDR.lower()]) == FILLS_PER_ADDRESS


def test_no_addresses_is_inert():
    ww = WhaleWatch("https://example", [])
    ww.start()                                           # no conecta, no revienta
    ww.ensure_alive()
    assert ww.recent() == {}
