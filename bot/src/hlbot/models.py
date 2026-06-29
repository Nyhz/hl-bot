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
