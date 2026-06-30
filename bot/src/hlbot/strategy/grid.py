from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)


class GridStrategy:
    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.lower: float | None = None
        self.upper: float | None = None
        self.levels: list[float] = []

    def set_anchor(self, mid: float) -> None:
        self.lower = mid * (1 - self.cfg.grid_range_pct)
        self.upper = mid * (1 + self.cfg.grid_range_pct)
        step = (self.upper - self.lower) / self.cfg.grid_n
        self.levels = [self.lower + step * i for i in range(self.cfg.grid_n + 1)]

    def _rung_size(self, price: float) -> float:
        # Cada rung es una posición del tamaño configurado (max_position_notional,
        # default $10 = mínimo de HL). El mínimo lo garantiza place_limit redondeando arriba.
        return self.cfg.limits.max_position_notional / price

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        out: list[Trigger] = []
        for lvl in self.levels:
            if lvl < ms.mid:
                out.append(Trigger(ms.coin, lvl, Side.BUY, "place_limit",
                                   f"compra maker en {lvl:.4f}"))
            elif lvl > ms.mid:
                out.append(Trigger(ms.coin, lvl, Side.SELL, "place_limit",
                                   f"venta maker en {lvl:.4f}"))
        return out

    def conditions(self, ms: MarketState) -> list[Condition]:
        if self.lower is None or self.upper is None:
            return []
        return [
            Condition("precio_sobre_limite_inferior", ms.mid, self.lower, ms.mid >= self.lower),
            Condition("precio_bajo_limite_superior", ms.mid, self.upper, ms.mid <= self.upper),
        ]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        if self.lower is None or self.upper is None:
            return []
        if ms.mid < self.lower or ms.mid > self.upper:
            return [Decision(ms.coin, ActionType.CLOSE, reduce_only=True,
                             reason="precio fuera de rango (range-exit stop)")]
        out: list[Decision] = []
        for lvl in self.levels:
            if lvl < ms.mid:
                side = Side.BUY
            elif lvl > ms.mid:
                side = Side.SELL
            else:
                continue
            out.append(Decision(ms.coin, ActionType.PLACE_LIMIT, side=side,
                                price=lvl, size=self._rung_size(lvl),
                                reason=f"grid rung {lvl:.4f}"))
        return out
