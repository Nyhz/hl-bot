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
