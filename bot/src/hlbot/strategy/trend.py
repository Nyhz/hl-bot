from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)
from hlbot.indicators import ema, adx, atr


class TrendOverlayStrategy:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg

    def _signals(self, ms: MarketState):
        closes = [c.close for c in ms.candles]
        highs = [c.high for c in ms.candles]
        lows = [c.low for c in ms.candles]
        ef = ema(closes, self.cfg.ema_fast)[-1]
        es = ema(closes, self.cfg.ema_slow)[-1]
        adx_series = adx(highs, lows, closes, self.cfg.adx_period)
        adx_now = adx_series[-1]
        adx_prev = adx_series[-2] if len(adx_series) >= 2 else 0.0
        atr_ = atr(highs, lows, closes, self.cfg.atr_period)[-1]
        return ef, es, adx_now, adx_prev, atr_

    def is_trending(self, ms: MarketState) -> bool:
        if len(ms.candles) < self.cfg.ema_slow:
            return False
        ef, es, adx_now, adx_prev, _ = self._signals(ms)
        sep = abs(ef - es) / ms.mid if ms.mid else 0.0
        return (adx_now > self.cfg.adx_threshold
                and adx_now > adx_prev
                and sep > self.cfg.ema_sep_frac)

    def _size(self, price: float) -> float:
        # Tamaño de posición configurado (max_position_notional, default $10).
        return self.cfg.limits.max_position_notional / price

    def conditions(self, ms: MarketState) -> list[Condition]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, adx_, _, _ = self._signals(ms)
        return [
            Condition("adx", adx_, self.cfg.adx_threshold, adx_ > self.cfg.adx_threshold),
            Condition("ema_align", ef - es, 0.0, ef > es),
        ]

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, _, _, atr_ = self._signals(ms)
        if ef > es:
            side, stop = Side.SELL, ms.mid - self.cfg.atr_stop_mult * atr_
        elif ef < es:
            side, stop = Side.BUY, ms.mid + self.cfg.atr_stop_mult * atr_
        else:
            return []
        return [Trigger(ms.coin, stop, side, "set_stop",
                        f"trailing stop ATR en {stop:.4f}")]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        if len(ms.candles) < self.cfg.ema_slow:
            return []
        ef, es, adx_, _, atr_ = self._signals(ms)
        if adx_ <= self.cfg.adx_threshold:
            return []
        if ef > es:
            stop = ms.mid - self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.BUY,
                         size=self._size(ms.mid),
                         reason="tendencia alcista (ADX>umbral, EMA fast>slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.SELL, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="trailing stop ATR"),
            ]
        if ef < es:
            stop = ms.mid + self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.SELL,
                         size=self._size(ms.mid),
                         reason="tendencia bajista (ADX>umbral, EMA fast<slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.BUY, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="trailing stop ATR"),
            ]
        return []
