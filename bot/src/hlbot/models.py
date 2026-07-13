from __future__ import annotations
from dataclasses import dataclass, field, asdict
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
    inventory: float = 0.0
    # Microestructura en vivo (WebSocket). None = sin dato fresco (REST puro o
    # backtest): las estrategias DEGRADAN a mid/ATR cuando faltan.
    best_bid: float | None = None
    best_ask: float | None = None
    bid_sz: float | None = None
    ask_sz: float | None = None
    microprice: float | None = None
    sigma_px: float | None = None       # vol realizada proyectada, en unidades de precio
    flow_usd: float | None = None       # USD firmado del tape (ventana corta)
    flow_ratio: float | None = None     # firmado/total en [-1, 1]; None sin volumen


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
    # Tope de notional (posición abierta) por moneda. Default permisivo: el cap real
    # de producción llega desde el form/API; aquí no estorba a los tests.
    max_coin_notional: float = 1e9


@dataclass
class SessionConfig:
    watchlist: list[str]
    capital: float
    limits: RiskLimits
    grid_n: int = 10
    grid_range_pct: float = 0.02        # clamp de rango máximo del grid respecto a la referencia
    ema_fast: int = 9
    ema_slow: int = 21
    adx_period: int = 14
    adx_threshold: float = 25.0
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    # Avellaneda-Stoikov + funding
    skew_strength: float = 1.5
    spread_vol_mult: float = 0.5
    min_spread_frac: float = 0.001
    funding_tilt: float = 0.3
    funding_min: float = 0.00005
    ema_sep_frac: float = 0.001


@dataclass
class Position:
    coin: str
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0


def session_config_from_dict(d: dict) -> SessionConfig:
    # Inverso de to_dict(SessionConfig) para rehidratar sesiones. Campos
    # desconocidos (payload de una versión más nueva) -> TypeError, que el
    # arranque trata como "no rehidratable" y archiva la sesión.
    d = dict(d)
    d["limits"] = RiskLimits(**d["limits"])
    return SessionConfig(**d)


def _convert(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):          # asdict already flattened dataclasses to dicts
        return {k: _convert(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def to_dict(obj) -> dict:
    return {k: _convert(v) for k, v in asdict(obj).items()}
