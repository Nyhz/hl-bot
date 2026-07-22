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
    flow_total_usd: float | None = None  # USD total del tape en la misma ventana
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
    # Tope de DELTA NETO agregado en $ (Σ notional firmado entre monedas): los
    # majors correlacionan >0.8, así que N longs "diversificados" son una sola
    # posición grande. Default permisivo por el mismo motivo que arriba.
    max_net_delta: float = 1e9


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
    # Entradas de momentum (PLACE_MARKET + stops). Con False el régimen de
    # tendencia solo actúa de FRENO del grid: se retira el lado que añade
    # exposición contra el movimiento y se sigue cotizando el resto (soak 2:
    # 4/4 entradas perdedoras y 53 retiradas completas del grid).
    trend_entries: bool = True
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    # Avellaneda-Stoikov + funding
    skew_strength: float = 1.5
    spread_vol_mult: float = 0.5
    min_spread_frac: float = 0.001
    funding_tilt: float = 0.3
    funding_min: float = 0.00005
    ema_sep_frac: float = 0.001
    # Microestructura (grid A-S v2). Solo actúan con WebSocket fresco; sin él
    # (backtest, WS caído) el grid degrada exactamente al comportamiento v1.
    microprice_weight: float = 0.3       # peso del microprice en el fair value
    ofi_weight: float = 0.5              # término de order-flow en la reserva (× sigma)
    toxicity_flow_ratio: float = 0.7     # |flow_ratio| que dispara la retirada
    toxicity_min_usd: float = 20000.0    # volumen mínimo en ventana para fiarse de la señal
    toxicity_cooldown_s: float = 30.0    # cuánto tiempo retirarse tras dispararse
    # Vol-sizing del rung: notional = clamp(risk_per_rung_usd / (sigma/mid),
    # $10 mínimo de HL, max_position_notional). 0 = desactivado (tamaño fijo v1).
    # Solo muerde si max_position_notional > $10 (el mínimo de HL es el suelo).
    risk_per_rung_usd: float = 0.0


# Perfil operativo canónico (análisis del soak 2 + sweep de backtests,
# 2026-07-19: suelo 15 bps + grid_n 3 multiplicó ×4-5 el PnL del soak). El
# launch expone únicamente capital y pérdida máxima: los parámetros de
# rentabilidad NO se eligen por sesión.
# Momentum APAGADO del todo: las entradas perdieron 4/4 en vivo, y el freno por
# lado (trend_entries=False + ADX 25) perdió contra el grid puro en el A/B de
# backtest (ETH -0.43 vs +0.42; el régimen ADX llega tarde y vende suelos). El
# adx_threshold=999 desactiva también el freno; el código queda para cuando
# haya una señal de régimen mejor calibrada en mainnet.
PROFILE_WATCHLIST = ["BTC", "ETH"]


def tuned_session_config(capital: float, max_loss: float) -> SessionConfig:
    # daily = total/2 (relación del soak 2): daily=total autorizaba a perder
    # el tope entero en un solo día sin haber visto aún un día de tendencia
    # fuerte con este perfil (análisis final soak 3, 2026-07-22).
    limits = RiskLimits(
        max_position_notional=10.0, max_open_positions=2, max_leverage=2.0,
        daily_loss_limit=max_loss / 2, total_loss_limit=max_loss,
        max_coin_notional=30.0, max_net_delta=45.0)
    return SessionConfig(
        watchlist=list(PROFILE_WATCHLIST), capital=capital, limits=limits,
        grid_n=3, min_spread_frac=0.0015,
        trend_entries=False, adx_threshold=999.0)


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
