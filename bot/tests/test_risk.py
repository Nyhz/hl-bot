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

def test_already_open_coin_bypasses_max_positions():
    # añadir a una moneda YA abierta no aumenta el nº de posiciones: en el cap
    # no debe rechazarse (bloquearlo congela el grid — soak de la sesión 5)
    ok, _ = _rm().can_open(notional=10.0, open_positions=2, leverage=1.0,
                           already_open=True)
    assert ok is True

def test_already_open_still_enforces_notional_and_leverage():
    ok, _ = _rm().can_open(notional=20.0, open_positions=2, leverage=1.0,
                           already_open=True)
    assert ok is False
    ok, _ = _rm().can_open(notional=10.0, open_positions=2, leverage=3.0,
                           already_open=True)
    assert ok is False

def test_should_pause_on_daily_loss():
    pause, reason = _rm().should_pause(daily_pnl=-6.0, total_pnl=-6.0)
    assert pause is True and "diaria" in reason

def test_no_pause_when_within_limits():
    pause, _ = _rm().should_pause(daily_pnl=-1.0, total_pnl=-1.0)
    assert pause is False

def test_should_pause_on_total_loss():
    # daily dentro de límite (-1 > -5), total cruza (-21 <= -20)
    pause, reason = _rm().should_pause(daily_pnl=-1.0, total_pnl=-21.0)
    assert pause is True and "total" in reason

def test_notional_at_limit_is_allowed():
    ok, _ = _rm().can_open(notional=15.0, open_positions=0, leverage=1.0)
    assert ok is True  # notional == max usa '>' estricto, no rechaza

def test_leverage_at_limit_is_allowed():
    ok, _ = _rm().can_open(notional=10.0, open_positions=0, leverage=2.0)
    assert ok is True  # leverage == max usa '>' estricto, no rechaza

def test_daily_loss_at_exact_limit_pauses():
    pause, _ = _rm().should_pause(daily_pnl=-5.0, total_pnl=-5.0)
    assert pause is True  # -5.0 <= -5.0 (límite inclusivo)
