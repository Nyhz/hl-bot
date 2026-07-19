from __future__ import annotations
from hlbot.models import RiskLimits


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def can_open(self, notional: float, open_positions: int,
                 leverage: float, already_open: bool = False) -> tuple[bool, str]:
        if notional > self.limits.max_position_notional:
            return False, "excede max_position_notional"
        # max_open_positions limita el Nº de monedas con posición: añadir a una
        # ya abierta no lo aumenta. Bloquearlo congela el grid en cuanto todas
        # las monedas de la watchlist tienen posición (sin rungs de entrada no
        # hay round-trips: solo queda el lado que reduce).
        if not already_open and open_positions >= self.limits.max_open_positions:
            return False, "max_open_positions alcanzado"
        if leverage > self.limits.max_leverage:
            return False, "excede max_leverage"
        return True, ""

    def should_pause(self, daily_pnl: float, total_pnl: float) -> tuple[bool, str]:
        if daily_pnl <= -self.limits.daily_loss_limit:
            return True, "limite de perdida diaria alcanzado"
        if total_pnl <= -self.limits.total_loss_limit:
            return True, "limite de perdida total alcanzado"
        return False, ""
