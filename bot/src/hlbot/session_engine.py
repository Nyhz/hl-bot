from __future__ import annotations
from hlbot.models import (
    MarketState, SessionState, SessionConfig, ActionType, Side, to_dict,
)
from hlbot.strategy.grid import GridStrategy
from hlbot.strategy.trend import TrendOverlayStrategy
from hlbot.risk import RiskManager


class SessionEngine:
    def __init__(self, client, store):
        self.client = client
        self.store = store
        self.state = SessionState.IDLE
        self.paused = False
        self.cfg: SessionConfig | None = None
        self.session_id: int | None = None
        self.risk: RiskManager | None = None
        self.grids: dict[str, GridStrategy] = {}
        self.trends: dict[str, TrendOverlayStrategy] = {}

    def launch(self, cfg: SessionConfig) -> None:
        if self.state != SessionState.IDLE:
            raise RuntimeError(f"no se puede lanzar en estado {self.state}")
        self.cfg = cfg
        self.risk = RiskManager(cfg.limits)
        self.session_id = self.store.create_session(cfg.watchlist, cfg.capital)
        self.grids = {}
        self.trends = {}
        for coin in cfg.watchlist:
            g = GridStrategy(cfg)
            g.set_anchor(self.client.mid(coin))
            self.grids[coin] = g
            self.trends[coin] = TrendOverlayStrategy(cfg)
        self.paused = False
        self.state = SessionState.SCANNING

    def close(self) -> None:
        if self.state in (SessionState.SCANNING, SessionState.ACTIVE):
            self.state = SessionState.CLOSING

    def kill(self, confirm: bool) -> None:
        if not confirm:
            raise ValueError("kill requiere confirmacion explicita")
        if self.cfg:
            for coin in self.cfg.watchlist:
                self.client.cancel_all(coin)
                self.client.market_close(coin)
        if self.session_id is not None:
            self.store.end_session(self.session_id)
        self._reset()

    def _reset(self) -> None:
        self.state = SessionState.IDLE
        self.paused = False
        self.cfg = None
        self.session_id = None
        self.risk = None
        self.grids = {}
        self.trends = {}

    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if trend.is_trending(ms):
            return trend.evaluate(ms)  # tendencia: pausa el grid de este par
        return grid.evaluate(ms)

    def _open_positions_count(self) -> int:
        state = self.client.user_state()
        return len(state.get("assetPositions", []))

    def tick(self, market_states: dict[str, MarketState]) -> None:
        if self.state == SessionState.IDLE or self.cfg is None:
            return
        n_open = self._open_positions_count()
        for coin, ms in market_states.items():
            if coin not in self.grids:
                continue
            decisions = self._decisions_for(ms)
            for d in decisions:
                # En CLOSING solo se permiten reduce_only / cierres.
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                self._apply(coin, ms, d, n_open)
        if self.state == SessionState.CLOSING and n_open == 0:
            self._reset()

    def _apply(self, coin: str, ms: MarketState, d, n_open: int) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            if not d.reduce_only:
                notional = (d.price or 0) * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_LIMIT requiere side")
            self.client.place_limit(coin, d.side == Side.BUY, d.price, d.size,
                                    post_only=True, reduce_only=d.reduce_only)
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.PLACE_MARKET:
            if not d.reduce_only:
                notional = ms.mid * (d.size or 0)
                ok, reason = self.risk.can_open(notional, n_open,
                                                self.cfg.limits.max_leverage)
                if not ok:
                    self.store.record_risk_event(self.session_id, "rechazo", reason)
                    return
            if d.side is None:
                raise ValueError("PLACE_MARKET requiere side")
            self.client.place_limit(coin, d.side == Side.BUY, ms.mid, d.size,
                                    post_only=False, reduce_only=d.reduce_only)
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            self.client.market_close(coin)
        self.store.record_decision(self.session_id, coin, d.action.value, d.reason)

    def snapshot(self, market_states: dict[str, MarketState] | None = None) -> dict:
        coins: dict[str, dict] = {}
        if self.cfg and market_states:
            for coin, ms in market_states.items():
                if coin not in self.grids:
                    continue
                grid = self.grids[coin]
                trend = self.trends[coin]
                trending = trend.is_trending(ms)
                active = trend if trending else grid
                coins[coin] = {
                    "mid": ms.mid,
                    "mode": "trend" if trending else "grid",
                    "triggers": [to_dict(t) for t in active.armed_triggers(ms)],
                    "conditions": [to_dict(c) for c in active.conditions(ms)],
                }
        return {
            "state": self.state.value,
            "paused": self.paused,
            "watchlist": self.cfg.watchlist if self.cfg else [],
            "coins": coins,
        }
