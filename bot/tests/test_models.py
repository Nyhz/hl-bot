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
