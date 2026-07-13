from __future__ import annotations
from hlbot.models import (
    MarketState, Decision, Trigger, Condition, Side, ActionType, SessionConfig,
)
from hlbot.indicators import atr


class GridStrategy:
    """Grid estilo Avellaneda-Stoikov: precio de referencia que se re-centra con el
    inventario, spread proporcional a la volatilidad (ATR) y sesgo por funding."""

    def __init__(self, cfg: SessionConfig):
        self.cfg = cfg
        self.anchor: float | None = None

    def set_anchor(self, mid: float) -> None:
        # Compat con launch(); A-S no usa ancla fija, pero guardamos el mid de arranque.
        self.anchor = mid

    def _sigma(self, ms: MarketState) -> float:
        # Vol realizada del WS si está fresca (reacciona en segundos); ATR de
        # velas 1m como fallback (backtest / WS caído) — comportamiento v1.
        if ms.sigma_px is not None and ms.sigma_px > 0:
            return ms.sigma_px
        if len(ms.candles) < self.cfg.atr_period + 1:
            return 0.0
        closes = [c.close for c in ms.candles]
        highs = [c.high for c in ms.candles]
        lows = [c.low for c in ms.candles]
        return atr(highs, lows, closes, self.cfg.atr_period)[-1]

    def _fair(self, ms: MarketState) -> float:
        # Fair value = blend mid/microprice: el microprice anticipa hacia dónde
        # empuja el desequilibrio del BBO. Sin WS -> mid (v1).
        if ms.microprice is None:
            return ms.mid
        w = self.cfg.microprice_weight
        return (1.0 - w) * ms.mid + w * ms.microprice

    def too_toxic(self, ms: MarketState) -> bool:
        # Flujo agresivo unidireccional con volumen suficiente: mejor retirarse
        # que ser la liquidez contra la que corre el mercado.
        if ms.flow_ratio is None or ms.flow_total_usd is None:
            return False
        if ms.flow_total_usd < self.cfg.toxicity_min_usd:
            return False
        return abs(ms.flow_ratio) > self.cfg.toxicity_flow_ratio

    def _phi_target(self, ms: MarketState) -> float:
        # Fracción objetivo de inventario (de max_coin_notional) según funding.
        # Funding positivo → phi_target negativo (sesgo corto): e = phi - phi_target > 0
        # cuando inventory es flat → res = mid - e*k*sigma < mid (sell rungs más cerca
        # del mid → se llenan antes → acumula corto para cobrar funding).
        f = ms.funding_rate
        if f is None or abs(f) < self.cfg.funding_min:
            return 0.0
        return -(1.0 if f > 0 else -1.0) * self.cfg.funding_tilt

    def reservation_price(self, ms: MarketState, sigma: float) -> float:
        cap = self.cfg.limits.max_coin_notional
        q_notional = ms.inventory * ms.mid
        phi = max(-1.0, min(1.0, q_notional / cap)) if cap > 0 else 0.0
        e = phi - self._phi_target(ms)
        res = self._fair(ms) - e * self.cfg.skew_strength * sigma
        # Término OFI: flujo agresivo comprador sube la reserva (no vender barato
        # a un mercado que empuja); vendedor la baja. Sin tape -> 0 (v1).
        if ms.flow_ratio is not None:
            res += self.cfg.ofi_weight * ms.flow_ratio * sigma
        return res

    def half_spread(self, ms: MarketState, sigma: float) -> float:
        return max(self.cfg.min_spread_frac * ms.mid, self.cfg.spread_vol_mult * sigma)

    def _rung_size(self, price: float) -> float:
        return self.cfg.limits.max_position_notional / price

    def _ladder(self, ms: MarketState) -> tuple[float, float, list[tuple[float, Side]]]:
        sigma = self._sigma(ms)
        res = self.reservation_price(ms, sigma)
        h = self.half_spread(ms, sigma)
        rungs: list[tuple[float, Side]] = []
        if h <= 0:
            return sigma, res, rungs
        max_dist = self.cfg.grid_range_pct * res
        for i in range(1, self.cfg.grid_n + 1):
            buy = res - i * h
            sell = res + i * h
            if buy < ms.mid and (res - buy) <= max_dist:
                rungs.append((buy, Side.BUY))
            if sell > ms.mid and (sell - res) <= max_dist:
                rungs.append((sell, Side.SELL))
        return sigma, res, rungs

    def desired_prices(self, ms: MarketState) -> list[float]:
        _, _, rungs = self._ladder(ms)
        return [p for p, _ in rungs]

    def evaluate(self, ms: MarketState) -> list[Decision]:
        # Sin range-exit por precio: con re-centrado la referencia sigue al mid, así que
        # esa salida quedaría muerta. La protección es el cap de inventario
        # (max_coin_notional, bloquea crecimiento) + los límites de pérdida de sesión (auto-close).
        sigma, res, rungs = self._ladder(ms)
        out: list[Decision] = []
        for price, side in rungs:
            out.append(Decision(ms.coin, ActionType.PLACE_LIMIT, side=side,
                                price=price, size=self._rung_size(price),
                                reason=f"grid rung {price:.4f} (res {res:.2f})"))
        return out

    def armed_triggers(self, ms: MarketState) -> list[Trigger]:
        _, _, rungs = self._ladder(ms)
        return [Trigger(ms.coin, p, s, "place_limit",
                        f"{'compra' if s == Side.BUY else 'venta'} maker en {p:.4f}")
                for p, s in rungs]

    def conditions(self, ms: MarketState) -> list[Condition]:
        sigma, res, rungs = self._ladder(ms)
        max_dist = self.cfg.grid_range_pct * res
        return [
            Condition("en_rango", abs(ms.mid - res), max_dist, abs(ms.mid - res) <= max_dist),
            Condition("rungs_activos", float(len(rungs)), 0.0, len(rungs) > 0),
        ]
