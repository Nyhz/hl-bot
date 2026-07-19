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

    def direction(self, ms: MarketState) -> int:
        # +1 tendencia alcista (EMA fast>slow), -1 bajista, 0 sin señal.
        if len(ms.candles) < self.cfg.ema_slow:
            return 0
        ef, es, *_ = self._signals(ms)
        if ef > es:
            return 1
        if ef < es:
            return -1
        return 0

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
        ef, es, adx_now, adx_prev, atr_ = self._signals(ms)
        if abs(ms.inventory) > 0:
            long = ms.inventory > 0
            # salida por reversión
            if (long and ef < es) or (not long and ef > es):
                return [Decision(ms.coin, ActionType.CLOSE, reduce_only=True,
                                 reason="reversión de tendencia (recruce EMA)")]
            # trailing stop deseado
            if long:
                stop = ms.mid - self.cfg.atr_stop_mult * atr_
                side = Side.SELL
            else:
                stop = ms.mid + self.cfg.atr_stop_mult * atr_
                side = Side.BUY
            return [Decision(ms.coin, ActionType.SET_STOP, side=side, price=stop,
                             size=abs(ms.inventory), reduce_only=True, reason="trailing stop ATR")]
        # flat: entrada solo si la tendencia está confirmada (is_trending filtra todo)
        if not self.is_trending(ms):
            return []
        if ef > es:
            stop = ms.mid - self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.BUY,
                         size=self._size(ms.mid), reason="tendencia alcista (ADX>umbral, EMA fast>slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.SELL, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="stop inicial ATR"),
            ]
        if ef < es:
            stop = ms.mid + self.cfg.atr_stop_mult * atr_
            return [
                Decision(ms.coin, ActionType.PLACE_MARKET, side=Side.SELL,
                         size=self._size(ms.mid), reason="tendencia bajista (ADX>umbral, EMA fast<slow)"),
                Decision(ms.coin, ActionType.SET_STOP, side=Side.BUY, price=stop,
                         size=self._size(ms.mid), reduce_only=True, reason="stop inicial ATR"),
            ]
        return []
