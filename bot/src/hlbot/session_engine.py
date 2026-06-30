from __future__ import annotations
import time
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
        self.session_started_at: int | None = None
        self.risk: RiskManager | None = None
        self.grids: dict[str, GridStrategy] = {}
        self.trends: dict[str, TrendOverlayStrategy] = {}
        self.session_start_value: float = 0.0
        self.day_anchor_value: float = 0.0
        self.day_anchor_date = None
        self.trend_open: set[str] = set()
        self.stops_placed: set[str] = set()
        self.trend_confirmed: set[str] = set()
        self.trend_regime: set[str] = set()

    def launch(self, cfg: SessionConfig) -> None:
        if self.state != SessionState.IDLE:
            raise RuntimeError(f"no se puede lanzar en estado {self.state}")
        pos = cfg.limits.max_position_notional
        if pos < 10.0:
            raise ValueError(
                f"posicion {pos} por debajo del minimo de $10 de Hyperliquid")
        if cfg.grid_n * pos > cfg.capital:
            raise ValueError(
                f"capital {cfg.capital} insuficiente para grid_n={cfg.grid_n} "
                f"a ${pos}/posicion (necesita >= {cfg.grid_n * pos})")
        self.cfg = cfg
        self.risk = RiskManager(cfg.limits)
        testnet = getattr(getattr(self.client, "cfg", None), "testnet", True)
        self.session_id = self.store.create_session(
            cfg.watchlist, cfg.capital, mode="testnet" if testnet else "mainnet")
        self.grids = {}
        self.trends = {}
        for coin in cfg.watchlist:
            g = GridStrategy(cfg)
            g.set_anchor(self.client.mid(coin))
            self.grids[coin] = g
            self.trends[coin] = TrendOverlayStrategy(cfg)
            # Fija el leverage máximo (isolated) por moneda; no bloquea el launch si falla.
            try:
                self.client.set_leverage(coin, int(cfg.limits.max_leverage))
            except Exception as e:
                self.store.record_risk_event(
                    self.session_id, "leverage", f"no se pudo fijar leverage en {coin}: {e}")
        self.session_start_value = self._account_value()
        self.session_started_at = int(time.time())
        self.day_anchor_value = self.session_start_value
        self.day_anchor_date = self._today_local()
        self.trend_open = set()
        self.stops_placed = set()
        self.trend_confirmed = set()
        self.trend_regime = set()
        self.paused = False
        self.state = SessionState.SCANNING

    def close(self) -> None:
        if self.state in (SessionState.SCANNING, SessionState.ACTIVE):
            self.state = SessionState.CLOSING
            if self.cfg:
                for coin in self.cfg.watchlist:
                    self.client.cancel_all(coin)

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
        self.session_started_at = None
        self.risk = None
        self.grids = {}
        self.trends = {}
        self.session_start_value = 0.0
        self.day_anchor_value = 0.0
        self.day_anchor_date = None
        self.trend_open = set()
        self.stops_placed = set()
        self.trend_confirmed = set()
        self.trend_regime = set()

    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if trend.is_trending(ms):
            return trend.evaluate(ms)  # tendencia: pausa el grid de este par
        return grid.evaluate(ms)

    def _account_value(self) -> float:
        state = self.client.user_state()
        return float(state["marginSummary"]["accountValue"])

    def _today_local(self):
        from datetime import datetime
        return datetime.now().astimezone().date()

    def _check_loss_limits(self) -> None:
        if self.risk is None:
            return
        value = self._account_value()
        today = self._today_local()
        if today != self.day_anchor_date:
            self.day_anchor_value = value
            self.day_anchor_date = today
        total_pnl = value - self.session_start_value
        daily_pnl = value - self.day_anchor_value
        pause, reason = self.risk.should_pause(daily_pnl, total_pnl)
        if pause and self.state != SessionState.CLOSING:
            self.store.record_risk_event(self.session_id, "limite", reason)
            self.paused = True
            self.close()

    def _position_notionals(self, state: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in state.get("assetPositions", []):
            pos = p.get("position", {}) or {}
            coin = pos.get("coin")
            if coin:
                out[coin] = abs(float(pos.get("positionValue", 0) or 0))
        return out

    def _risk_ok(self, notional: float, n_open: int, equity: float,
                 gross: float, coin_notional: float) -> bool:
        # Leverage REAL = (notional bruto abierto + esta orden) / equity de la cuenta.
        lev = (gross + notional) / equity if equity > 0 else 1e9
        ok, reason = self.risk.can_open(notional, n_open, lev)
        if not ok:
            self.store.record_risk_event(self.session_id, "rechazo", reason)
            return False
        if coin_notional + notional > self.cfg.limits.max_coin_notional:
            self.store.record_risk_event(
                self.session_id, "rechazo", "excede max_coin_notional")
            return False
        return True

    def tick(self, market_states: dict[str, MarketState]) -> None:
        if self.state == SessionState.IDLE or self.cfg is None:
            return
        self._check_loss_limits()
        state = self.client.user_state()
        asset_positions = state.get("assetPositions", [])
        n_open = len(asset_positions)
        pos_notionals = self._position_notionals(state)
        open_coins = set(pos_notionals.keys())
        equity = float(state.get("marginSummary", {}).get("accountValue", 0) or 0)
        gross = sum(pos_notionals.values())
        pos_sizes = {}
        for p in asset_positions:
            pos = p.get("position", {}) or {}
            coin = pos.get("coin")
            if coin:
                pos_sizes[coin] = float(pos.get("szi", 0) or 0)
        # Confirmar posiciones de tendencia ya visibles; limpiar SOLO las que estaban
        # confirmadas y han desaparecido (stop ejecutado) -> evita doble entrada por
        # latencia de fill (la posición recién abierta aún no aparece en user_state).
        self.trend_confirmed |= (self.trend_open & open_coins)
        gone = self.trend_confirmed - open_coins
        self.trend_open -= gone
        self.stops_placed -= gone
        self.trend_confirmed -= gone
        for coin, ms in market_states.items():
            if coin not in self.grids:
                continue
            ms.inventory = pos_sizes.get(coin, 0.0)
            # #4: al entrar en régimen de tendencia, cancelar una vez el grid en reposo
            # (deja de mezclar inventario grid con la entrada de tendencia).
            trending = self.trends[coin].is_trending(ms)
            if trending and coin not in self.trend_regime:
                self.client.cancel_all(coin)
                self.trend_regime.add(coin)
            elif not trending:
                self.trend_regime.discard(coin)
            decisions = self._decisions_for(ms)
            grid_active = (coin not in self.trend_open
                           and not self.trends[coin].is_trending(ms))
            if grid_active and self.state != SessionState.CLOSING:
                self._reconcile_grid(coin, ms, decisions, n_open, equity, gross,
                                     pos_notionals.get(coin, 0.0))
            for d in decisions:
                if d.action == ActionType.PLACE_LIMIT and not d.reduce_only:
                    continue  # los PLACE_LIMIT de grid los gestiona _reconcile_grid
                if self.state == SessionState.CLOSING and not (
                    d.reduce_only or d.action in (ActionType.CLOSE, ActionType.SET_STOP)
                ):
                    continue
                self._apply(coin, ms, d, n_open, equity, gross,
                            pos_notionals.get(coin, 0.0))
        if self.state == SessionState.CLOSING and n_open == 0:
            self._reset()

    def _reconcile_grid(self, coin, ms, decisions, n_open, equity, gross, coin_notional) -> None:
        try:
            desired = [(d.price, d) for d in decisions if d.action == ActionType.PLACE_LIMIT]
            grid = self.grids[coin]
            tol = max(grid.half_spread(ms, grid._sigma(ms)) / 2.0, 1e-9)
            open_orders = self.client.open_orders(coin)
            # 1) cancelar stale: órdenes en reposo lejos de cualquier precio deseado
            for o in open_orders:
                px = float(o.get("limitPx", 0) or 0)
                oid = o.get("oid")
                if oid is None:
                    continue
                if not any(abs(px - dp) <= tol for dp, _ in desired):
                    self.client.cancel_order(coin, oid)
            # 2) colocar las deseadas que no tengan ya una orden cerca (guards vía _apply/_risk_ok)
            rest_px = [float(o.get("limitPx", 0) or 0) for o in open_orders]
            for dp, d in desired:
                if any(abs(dp - rp) <= tol for rp in rest_px):
                    continue
                self._apply(coin, ms, d, n_open, equity, gross, coin_notional)
        except Exception as e:
            self.store.record_risk_event(self.session_id, "reconcile_error", str(e))
            return

    def _apply(self, coin: str, ms: MarketState, d, n_open: int,
               equity: float, gross: float, coin_notional: float) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            if not d.reduce_only:
                notional = (d.price or 0) * (d.size or 0)
                if not self._risk_ok(notional, n_open, equity, gross, coin_notional):
                    return
            if d.side is None:
                raise ValueError("PLACE_LIMIT requiere side")
            try:
                self.client.place_limit(coin, d.side == Side.BUY, d.price, d.size,
                                        post_only=True, reduce_only=d.reduce_only)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.PLACE_MARKET:
            if not d.reduce_only and coin in self.trend_open:
                return
            if not d.reduce_only:
                notional = ms.mid * (d.size or 0)
                if not self._risk_ok(notional, n_open, equity, gross, coin_notional):
                    return
            if d.side is None:
                raise ValueError("PLACE_MARKET requiere side")
            try:
                self.client.market_open(coin, d.side == Side.BUY, d.size or 0.0)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            if not d.reduce_only:
                self.trend_open.add(coin)
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            self.client.market_close(coin)
        elif d.action == ActionType.SET_STOP:
            if coin in self.stops_placed or d.side is None or d.price is None:
                return
            self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0,
                                   reduce_only=True)
            self.stops_placed.add(coin)
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
                conds = active.conditions(ms)
                coins[coin] = {
                    "mid": ms.mid,
                    "mode": "trend" if trending else "grid",
                    "funding": ms.funding_rate,
                    "triggers": [to_dict(t) for t in active.armed_triggers(ms)],
                    "conditions": [to_dict(c) for c in conds],
                    "armed": all(c.met for c in conds) if conds else False,
                }
        testnet = getattr(getattr(self.client, "cfg", None), "testnet", True)
        return {
            "state": self.state.value,
            "paused": self.paused,
            "mode": "testnet" if testnet else "mainnet",
            "session_id": self.session_id,
            "session_started_at": self.session_started_at,
            "watchlist": self.cfg.watchlist if self.cfg else [],
            "coins": coins,
        }
