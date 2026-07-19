from __future__ import annotations
import json
import threading
import time
from datetime import date
from hlbot.models import (
    MarketState, SessionState, SessionConfig, ActionType, Side, to_dict,
    session_config_from_dict,
)
from hlbot.strategy.grid import GridStrategy
from hlbot.strategy.trend import TrendOverlayStrategy
from hlbot.risk import RiskManager
from hlbot.indicators import atr
from hlbot.hl_client import order_response_error, order_response_errors

PNL_SNAPSHOT_EVERY_TICKS = 12   # ~1/min a 5s/tick
REJECT_LOG_EVERY_S = 300.0      # un rechazo persistente se re-loguea cada 5 min,
                                # no cada tick (sesión 5: 230k filas del mismo motivo)


def _order_is_buy(o: dict) -> bool:
    # open_orders del exchange trae side "B"/"A"; el broker de backtest, is_buy.
    if "is_buy" in o:
        return bool(o["is_buy"])
    return str(o.get("side", "")) == "B"


class SessionEngine:
    def __init__(self, client, store):
        self.client = client
        self.store = store
        self.lock = threading.Lock()
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
        self.stop_levels: dict[str, float] = {}
        self.stop_oids: dict[str, int] = {}
        self.trend_confirmed: set[str] = set()
        self.trend_regime: set[str] = set()
        # coin -> epoch hasta el que el grid NO cotiza (toxicity gate). Estado
        # transitorio (≤cooldown): no se persiste; tras reiniciar se re-evalúa.
        self.toxic_until: dict[str, float] = {}
        self._net_delta = 0.0   # Σ notional firmado entre monedas (se recalcula por tick)
        # Reposo vivo por coin: (Σ notional de compras, Σ de ventas). Lo refresca
        # el reconciliador cada tick; los caps lo descuentan como peor caso.
        self._resting_adds: dict[str, tuple[float, float]] = {}
        self._tick_count = 0
        # (coin, motivo) -> (ts del último evento grabado, rechazos suprimidos desde
        # entonces). Solo throttle de logging; no persiste (se re-aprende al vuelo).
        self._reject_throttle: dict[tuple[str, str], tuple[float, int]] = {}

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
        # Config COMPLETA e inmutable del lanzamiento: sin esto un test run no se
        # puede analizar (sessions solo guardaba watchlist+capital).
        self.store.set_session_config(self.session_id, json.dumps(to_dict(cfg)))
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
        self.stop_levels = {}
        self.stop_oids = {}
        self.trend_confirmed = set()
        self.trend_regime = set()
        self.toxic_until = {}
        self._reject_throttle = {}
        self._resting_adds = {}
        self.paused = False
        self.state = SessionState.SCANNING
        self._save_runtime()

    def runtime_payload(self) -> dict:
        return {
            "cfg": to_dict(self.cfg),
            "state": self.state.value,
            "paused": self.paused,
            "session_start_value": self.session_start_value,
            "day_anchor_value": self.day_anchor_value,
            "day_anchor_date": self.day_anchor_date.isoformat()
                               if self.day_anchor_date else None,
            "trend_open": sorted(self.trend_open),
            "trend_confirmed": sorted(self.trend_confirmed),
            "trend_regime": sorted(self.trend_regime),
            "stop_levels": self.stop_levels,
            "stop_oids": self.stop_oids,
        }

    def _save_runtime(self) -> None:
        # Persistir no puede tumbar el trading: si la BD falla, log y seguir
        # (el snapshot del siguiente tick lo reintenta solo).
        if self.session_id is None or self.cfg is None:
            return
        try:
            self.store.save_runtime(self.session_id, json.dumps(self.runtime_payload()))
        except Exception as e:
            print(f"[runtime] error guardando: {e}", flush=True)

    def rehydrate(self, session_id: int, started_at: int, payload: dict) -> None:
        """Reconstruye una sesión viva desde su snapshot tras un reinicio del proceso.

        Las estrategias son deterministas de la cfg (sin estado propio), así que
        basta restaurar el estado del engine y reconciliar contra el exchange,
        que es la verdad: posiciones cerradas o stops cancelados con el bot
        muerto se olvidan aquí.
        """
        cfg = session_config_from_dict(payload["cfg"])
        self.cfg = cfg
        self.risk = RiskManager(cfg.limits)
        self.session_id = session_id
        self.session_started_at = started_at
        self.grids = {coin: GridStrategy(cfg) for coin in cfg.watchlist}
        self.trends = {coin: TrendOverlayStrategy(cfg) for coin in cfg.watchlist}
        self.session_start_value = float(payload.get("session_start_value", 0.0))
        self.day_anchor_value = float(
            payload.get("day_anchor_value", self.session_start_value))
        d = payload.get("day_anchor_date")
        self.day_anchor_date = date.fromisoformat(d) if d else self._today_local()
        self.trend_open = set(payload.get("trend_open", []))
        self.trend_confirmed = set(payload.get("trend_confirmed", []))
        self.trend_regime = set(payload.get("trend_regime", []))
        self.stop_levels = {c: float(v) for c, v in
                            (payload.get("stop_levels") or {}).items()}
        self.stop_oids = {c: v for c, v in (payload.get("stop_oids") or {}).items()
                          if v is not None}
        self.paused = bool(payload.get("paused", False))
        try:
            self.state = SessionState(payload.get("state", "scanning"))
        except ValueError:
            self.state = SessionState.SCANNING
        if self.state == SessionState.IDLE:      # nunca debería persistirse, pero por si acaso
            self.state = SessionState.SCANNING
        self._reconcile_after_rehydrate()
        self._save_runtime()

    def _reconcile_after_rehydrate(self) -> None:
        try:
            state = self.client.user_state()
        except Exception as e:
            # Sin red al arrancar: mantener lo persistido; el tick reconcilia después.
            self.store.record_risk_event(self.session_id, "rehydrate",
                                         f"user_state: {e}")
            return
        open_coins = {c for c in ((p.get("position", {}) or {}).get("coin")
                                  for p in state.get("assetPositions", [])) if c}
        # Posición de tendencia cerrada con el bot muerto (stop ejecutado): fuera,
        # y su trigger residual (si quedara) se cancela.
        for c in sorted(self.trend_open - open_coins):
            oid = self.stop_oids.pop(c, None)
            self.stop_levels.pop(c, None)
            if oid is not None:
                try:
                    self.client.cancel_order(c, oid)
                except Exception:
                    pass
        self.trend_open &= open_coins
        # Con la posición ya visible, lo rehidratado abierto queda confirmado.
        self.trend_confirmed = set(self.trend_open)
        # Stops rastreados cuyo trigger ya no existe en el exchange (p.ej. el
        # watchdog canceló el reposo... los triggers no, pero un kill parcial sí
        # pudo): olvidarlos para que el engine los recoloque al siguiente tick.
        try:
            trigger_oids = {o.get("oid") for o in self.client.frontend_open_orders()}
        except Exception as e:
            self.store.record_risk_event(self.session_id, "rehydrate",
                                         f"frontend_open_orders: {e}")
            return
        for c, oid in list(self.stop_oids.items()):
            if oid not in trigger_oids:
                self.stop_oids.pop(c, None)
                self.stop_levels.pop(c, None)

    def close(self) -> None:
        if self.state not in (SessionState.SCANNING, SessionState.ACTIVE):
            raise RuntimeError(
                f"no hay sesion activa que cerrar (estado {self.state.value})")
        self.state = SessionState.CLOSING
        if self.cfg:
            for coin in self.cfg.watchlist:
                try:
                    self.client.cancel_all(coin)
                    self._resting_adds[coin] = (0.0, 0.0)
                except Exception as e:
                    self.store.record_risk_event(
                        self.session_id, "close_error", f"cancel_all {coin}: {e}")
        self._save_runtime()   # un Close en curso sobrevive a un reinicio

    def kill(self, confirm: bool) -> None:
        if not confirm:
            raise ValueError("kill requiere confirmacion explicita")
        errors: list[str] = []
        try:
            positions = self.client.user_state().get("assetPositions", [])
        except Exception as e:
            positions = []
            errors.append(f"user_state: {e}")
        pos_coins = {(p.get("position", {}) or {}).get("coin") for p in positions}
        pos_coins.discard(None)
        # watchlist ∪ posiciones reales: cubre huérfanas post-reinicio (cfg perdida)
        # y fills recientes aún no visibles en user_state.
        coins = sorted(pos_coins | set(self.cfg.watchlist if self.cfg else []))
        for coin in coins:
            try:
                self.client.cancel_all(coin)
                self._resting_adds[coin] = (0.0, 0.0)
            except Exception as e:
                errors.append(f"cancel_all {coin}: {e}")
            try:
                err = order_response_error(self.client.market_close(coin))
            except Exception as e:
                err = str(e)
            if err and coin in pos_coins:
                errors.append(f"market_close {coin}: {err}")
        # Verificación final contra el exchange: kill solo "triunfa" si quedamos planos.
        try:
            remaining = sorted({c for c in ((p.get("position", {}) or {}).get("coin")
                                for p in self.client.user_state().get("assetPositions", []))
                                if c})
        except Exception as e:
            remaining = None
            errors.append(f"verificacion final: {e}")
        if remaining:
            errors.append(f"posiciones aun abiertas: {', '.join(remaining)}")
        if self.session_id is not None:
            for msg in errors:
                self.store.record_risk_event(self.session_id, "kill_error", msg)
        if remaining != []:
            raise RuntimeError("kill incompleto: " + "; ".join(errors))
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
        self.stop_levels = {}
        self.stop_oids = {}
        self.trend_confirmed = set()
        self.trend_regime = set()
        self.toxic_until = {}
        self._reject_throttle = {}
        self._resting_adds = {}

    def _decisions_for(self, ms: MarketState) -> list:
        trend = self.trends[ms.coin]
        grid = self.grids[ms.coin]
        if ms.coin in self.trend_open:        # posición de tendencia -> la gestiona momentum
            return trend.evaluate(ms)
        if abs(ms.inventory) > 1e-12:          # posición de grid abierta -> la gestiona el grid
            return grid.evaluate(ms)           #   (aunque el régimen sea de tendencia)
        if trend.is_trending(ms):              # plano + tendencia -> momentum puede entrar
            if not self.cfg.trend_entries:     # ...salvo con entradas apagadas: el
                return grid.evaluate(ms)       # régimen solo filtra lados del grid
            return trend.evaluate(ms)
        return grid.evaluate(ms)               # plano + lateral -> grid

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

    def _record_reject(self, coin: str, reason: str) -> None:
        # Un guard que rechaza lo re-intenta CADA tick: sin throttle el mismo
        # motivo genera decenas de miles de risk_events al día.
        now = time.time()
        key = (coin, reason)
        last_ts, suppressed = self._reject_throttle.get(key, (0.0, 0))
        if now - last_ts < REJECT_LOG_EVERY_S:
            self._reject_throttle[key] = (last_ts, suppressed + 1)
            return
        detail = f"{coin}: {reason}"
        if suppressed:
            detail += f" (+{suppressed} suprimidos)"
        self.store.record_risk_event(self.session_id, "rechazo", detail)
        self._reject_throttle[key] = (now, 0)

    def _risk_ok(self, coin: str, notional: float, n_open: int, equity: float,
                 gross: float, coin_notional: float,
                 signed_notional: float = 0.0, already_open: bool = False,
                 inv_usd: float | None = None,
                 rest_buy: float = 0.0, rest_sell: float = 0.0) -> bool:
        # Leverage REAL = (notional bruto abierto + esta orden) / equity de la cuenta.
        lev = (gross + notional) / equity if equity > 0 else 1e9
        ok, reason = self.risk.can_open(notional, n_open, lev,
                                        already_open=already_open)
        if not ok:
            self._record_reject(coin, reason)
            return False
        # FUGA del soak 2: el check era solo contra la POSICIÓN, pero la escalera
        # en reposo se llena después (net_delta llegó a -54 con cap 30). Los caps
        # se evalúan contra el PEOR CASO: inventario + reposo del mismo lado + esta
        # orden, todo firmado (así el lado que reduce sigue pasando siempre).
        is_buy = signed_notional >= 0
        if inv_usd is None:
            if coin_notional + notional > self.cfg.limits.max_coin_notional:
                self._record_reject(coin, "excede max_coin_notional")
                return False
        else:
            if is_buy:
                breach_coin = (inv_usd + rest_buy + notional
                               > self.cfg.limits.max_coin_notional)
            else:
                breach_coin = (inv_usd - rest_sell - notional
                               < -self.cfg.limits.max_coin_notional)
            if breach_coin:
                self._record_reject(coin, "excede max_coin_notional")
                return False
        # Delta neto de CARTERA: majors correlacionados -> N longs = 1 posición
        # grande. Peor caso direccional: si esta orden compra, todo el reposo
        # comprador (de todas las monedas) también puede llenarse.
        other_buy = sum(b for c, (b, s) in self._resting_adds.items() if c != coin)
        other_sell = sum(s for c, (b, s) in self._resting_adds.items() if c != coin)
        if is_buy:
            after = self._net_delta + other_buy + rest_buy + notional
            breach = after > self.cfg.limits.max_net_delta
        else:
            after = self._net_delta - other_sell - rest_sell - notional
            breach = after < -self.cfg.limits.max_net_delta
        if breach:
            self._record_reject(coin, "excede max_net_delta")
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
        net_delta = 0.0
        for p in asset_positions:
            pos = p.get("position", {}) or {}
            coin = pos.get("coin")
            if coin:
                szi = float(pos.get("szi", 0) or 0)
                pos_sizes[coin] = szi
                val = abs(float(pos.get("positionValue", 0) or 0))
                net_delta += val if szi > 0 else (-val if szi < 0 else 0.0)
        self._net_delta = net_delta
        # Confirmar posiciones de tendencia ya visibles; limpiar SOLO las que estaban
        # confirmadas y han desaparecido (stop ejecutado) -> evita doble entrada por
        # latencia de fill (la posición recién abierta aún no aparece en user_state).
        self.trend_confirmed |= (self.trend_open & open_coins)
        gone = self.trend_confirmed - open_coins
        self.trend_open -= gone
        self.trend_confirmed -= gone
        for c in gone:
            oid = self.stop_oids.get(c)
            if oid is not None:
                try:
                    self.client.cancel_order(c, oid)
                except Exception as e:
                    self.store.record_risk_event(self.session_id, "stop_error", str(e))
            self.stop_levels.pop(c, None)
            self.stop_oids.pop(c, None)
        micro_rows: list[dict] = []
        for coin, ms in market_states.items():
            if coin not in self.grids:
                continue
            ms.inventory = pos_sizes.get(coin, 0.0)
            micro_rows.append({
                "ts": int(time.time()), "coin": coin, "mid": ms.mid,
                "best_bid": ms.best_bid, "best_ask": ms.best_ask,
                "bid_sz": ms.bid_sz, "ask_sz": ms.ask_sz,
                "microprice": ms.microprice, "sigma_px": ms.sigma_px,
                "flow_usd": ms.flow_usd, "flow_total_usd": ms.flow_total_usd,
                "flow_ratio": ms.flow_ratio, "funding": ms.funding_rate,
                "inventory": ms.inventory,
                "toxic": 1 if time.time() < self.toxic_until.get(coin, 0.0) else 0,
            })
            trending = self.trends[coin].is_trending(ms)
            if self.cfg.trend_entries:
                # #4: al entrar en régimen de tendencia, cancelar una vez el grid en
                # reposo (deja de mezclar inventario grid con la entrada de tendencia).
                if (trending and coin not in self.trend_regime
                        and coin not in self.trend_open):
                    self.client.cancel_all(coin)
                    self._resting_adds[coin] = (0.0, 0.0)
                    self.trend_regime.add(coin)
                    self.store.record_decision(
                        self.session_id, coin, ActionType.CANCEL.value,
                        "régimen de tendencia: grid retirado")
                elif not trending:
                    self.trend_regime.discard(coin)
            else:
                # Freno por lado (soak 2): en tendencia el grid sigue cotizando,
                # pero sin rungs que añadan exposición CONTRA el movimiento; el
                # reconciliador cancela solos los del lado retirado (dejan de
                # estar en desired).
                if trending and coin not in self.trend_regime:
                    self.trend_regime.add(coin)
                    lado = ("comprador" if self.trends[coin].direction(ms) < 0
                            else "vendedor")
                    self.store.record_decision(
                        self.session_id, coin, ActionType.CANCEL.value,
                        f"freno de régimen: lado {lado} retirado")
                elif not trending:
                    self.trend_regime.discard(coin)
            decisions = self._decisions_for(ms)
            if not self.cfg.trend_entries and trending:
                decisions = self._regime_side_filter(coin, ms, decisions)
            grid_active = (coin not in self.trend_open
                           and (not trending if self.cfg.trend_entries else True))
            if grid_active and self.state != SessionState.CLOSING:
                if not self._toxicity_gate(coin, ms):
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
        # Series para el análisis de test runs: microestructura por tick y, cada
        # ~minuto, equity con exposición (unrealized/gross/net_delta/L1).
        self._tick_count += 1
        self.store.record_micro_batch(self.session_id, micro_rows)
        if self._tick_count % PNL_SNAPSHOT_EVERY_TICKS == 0:
            unrealized = sum(float((p.get("position", {}) or {}).get("unrealizedPnl", 0) or 0)
                             for p in asset_positions)
            self.store.record_pnl_snapshot(
                self.session_id, equity, unrealized=unrealized, gross=gross,
                net_delta=self._net_delta, open_count=n_open,
                l1_total=getattr(self.client, "l1_actions", {}).get("total"))
        if self.state == SessionState.CLOSING:
            if n_open == 0:
                if self.session_id is not None:
                    self.store.end_session(self.session_id)
                self._reset()
            else:
                self._force_close_positions(asset_positions)
        self._save_runtime()   # snapshot por tick (tras _reset es no-op)

    def _toxicity_gate(self, coin: str, ms: MarketState) -> bool:
        """True si el grid debe abstenerse de cotizar este tick (flujo tóxico).

        Al dispararse retira el reposo del grid una vez (solo se llama con
        grid_active, así que nunca toca el trailing stop de una tendencia) y
        mantiene la retirada durante el cooldown.
        """
        now = time.time()
        if now < self.toxic_until.get(coin, 0.0):
            return True
        if not self.grids[coin].too_toxic(ms):
            return False
        self.toxic_until[coin] = now + self.cfg.toxicity_cooldown_s
        try:
            self.client.cancel_all(coin)
            self._resting_adds[coin] = (0.0, 0.0)
        except Exception as e:
            self.store.record_risk_event(self.session_id, "toxicity", str(e))
        self.store.record_decision(
            self.session_id, coin, ActionType.CANCEL.value,
            f"toxicity gate: flow_ratio {ms.flow_ratio:+.2f} -> "
            f"retirada {int(self.cfg.toxicity_cooldown_s)}s")
        return True

    def _force_close_positions(self, asset_positions: list) -> None:
        # Cierre ACTIVO: el grid no tiene salida propia (solo coloca rungs), así que
        # en CLOSING no se puede esperar a que la posición "salga sola". Se liquida a
        # mercado verificando la respuesta y se reintenta cada tick hasta quedar plano.
        for p in asset_positions:
            coin = (p.get("position", {}) or {}).get("coin")
            if not coin:
                continue
            try:
                self.client.cancel_all(coin)
                self._resting_adds[coin] = (0.0, 0.0)
                err = order_response_error(self.client.market_close(coin))
            except Exception as e:
                err = str(e)
            if err:
                self.store.record_risk_event(
                    self.session_id, "close_error", f"{coin}: {err}")

    def _limit_allowed(self, ms, d, n_open, equity, gross, coin_notional,
                       rest_buy: float | None = None,
                       rest_sell: float | None = None) -> bool:
        # Un rung del lado contrario que no supera el inventario REDUCE la posición:
        # no debe pasar por can_open/max_coin_notional (bloquearlo congela la
        # posición en el cap sin vía de salida).
        reduces = ((d.side == Side.SELL and ms.inventory > 1e-12)
                   or (d.side == Side.BUY and ms.inventory < -1e-12))
        shrinks = reduces and (d.size or 0) <= abs(ms.inventory) + 1e-12
        if d.reduce_only or shrinks:
            return True
        notional = (d.price or 0) * (d.size or 0)
        signed = notional if d.side == Side.BUY else -notional
        rb, rs = self._resting_adds.get(ms.coin, (0.0, 0.0))
        return self._risk_ok(ms.coin, notional, n_open, equity, gross,
                             coin_notional, signed,
                             already_open=abs(ms.inventory) > 1e-12,
                             inv_usd=self._signed_inv_usd(ms, coin_notional),
                             rest_buy=rb if rest_buy is None else rest_buy,
                             rest_sell=rs if rest_sell is None else rest_sell)

    def _regime_side_filter(self, coin: str, ms, decisions: list) -> list:
        """Sin entradas de momentum, la tendencia solo VETA el lado del grid que
        añade exposición contra el movimiento (comprar toda una caída fue la
        captura negativa del 17-jul). Los rungs que reducen posición se quedan.
        """
        dir_ = self.trends[coin].direction(ms)
        if dir_ == 0:
            return decisions
        out = []
        for d in decisions:
            if d.action == ActionType.PLACE_LIMIT and not d.reduce_only:
                against = ((d.side == Side.BUY and dir_ < 0)
                           or (d.side == Side.SELL and dir_ > 0))
                adds = ((d.side == Side.BUY and ms.inventory >= -1e-12)
                        or (d.side == Side.SELL and ms.inventory <= 1e-12))
                if against and adds:
                    continue
            out.append(d)
        return out

    @staticmethod
    def _signed_inv_usd(ms, coin_notional: float) -> float | None:
        # Magnitud del positionValue (autoritativa) con el signo del szi. Si el
        # exchange da notional sin signo visible, None -> check legado (abs).
        if ms.inventory > 1e-12:
            return coin_notional
        if ms.inventory < -1e-12:
            return -coin_notional
        return 0.0 if coin_notional <= 1e-9 else None

    def _reconcile_grid(self, coin, ms, decisions, n_open, equity, gross, coin_notional) -> None:
        try:
            desired = [(d.price, d) for d in decisions if d.action == ActionType.PLACE_LIMIT]
            grid = self.grids[coin]
            # 0.75·half: con half/2 el 89% de las órdenes se cancelaba sin llenarse
            # (8.4k places / 933 fills en el soak 2) — churn que quema prioridad
            # de cola; una banda más ancha recoloca solo cuando de verdad toca.
            tol = max(grid.half_spread(ms, grid._sigma(ms)) * 0.75, 1e-9)
            open_orders = self.client.open_orders(coin)
            # 1) cancelar stale en UN batch: reposo lejos de cualquier precio deseado
            stale = [o["oid"] for o in open_orders
                     if o.get("oid") is not None
                     and not any(abs(float(o.get("limitPx", 0) or 0) - dp) <= tol
                                 for dp, _ in desired)]
            if stale:
                self.client.cancel_orders(coin, stale)
                self.store.record_decision(
                    self.session_id, coin, ActionType.CANCEL.value,
                    f"reconcile: {len(stale)} rungs stale retirados")
            # Reposo superviviente por lado: es exposición latente que los caps
            # deben descontar (la fuga del soak 2: el check era solo al colocar).
            stale_set = set(stale)
            keep = [o for o in open_orders if o.get("oid") not in stale_set]
            rest_buy = sum(float(o.get("limitPx", 0) or 0) * float(o.get("sz", 0) or 0)
                           for o in keep if _order_is_buy(o))
            rest_sell = sum(float(o.get("limitPx", 0) or 0) * float(o.get("sz", 0) or 0)
                            for o in keep if not _order_is_buy(o))
            self._resting_adds[coin] = (rest_buy, rest_sell)
            # 2) colocar las deseadas que falten, también en UN batch. El presupuesto
            # es SECUENCIAL: cada orden aprobada consume cap para las siguientes.
            rest_px = [float(o.get("limitPx", 0) or 0) for o in open_orders]
            to_place = []
            for dp, d in desired:
                if any(abs(dp - rp) <= tol for rp in rest_px):
                    continue
                if not self._limit_allowed(ms, d, n_open, equity, gross,
                                           coin_notional, rest_buy, rest_sell):
                    continue
                to_place.append(d)
                add = (d.price or 0) * (d.size or 0)
                if d.side == Side.BUY:
                    rest_buy += add
                else:
                    rest_sell += add
            self._resting_adds[coin] = (rest_buy, rest_sell)
            if not to_place:
                return
            if d_side_missing := [d for d in to_place if d.side is None]:
                raise ValueError(f"PLACE_LIMIT sin side: {d_side_missing[0].reason}")
            resp = self.client.bulk_place_limits(
                coin, [{"is_buy": d.side == Side.BUY, "price": d.price,
                        "size": d.size, "reduce_only": d.reduce_only} for d in to_place])
            placed_any = False
            for d, err in zip(to_place, order_response_errors(resp, len(to_place))):
                if err:
                    self.store.record_risk_event(
                        self.session_id, "orden_rechazada", f"{coin}: {err}")
                else:
                    placed_any = True
                    self.store.record_decision(self.session_id, coin,
                                               d.action.value, d.reason)
            if placed_any and self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        except Exception as e:
            self.store.record_risk_event(self.session_id, "reconcile_error", str(e))
            return

    def _apply(self, coin: str, ms: MarketState, d, n_open: int,
               equity: float, gross: float, coin_notional: float) -> None:
        if d.action == ActionType.PLACE_LIMIT:
            if not self._limit_allowed(ms, d, n_open, equity, gross, coin_notional):
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
                signed = notional if d.side == Side.BUY else -notional
                rb, rs = self._resting_adds.get(coin, (0.0, 0.0))
                if not self._risk_ok(coin, notional, n_open, equity, gross,
                                     coin_notional, signed,
                                     already_open=abs(ms.inventory) > 1e-12,
                                     inv_usd=self._signed_inv_usd(ms, coin_notional),
                                     rest_buy=rb, rest_sell=rs):
                    return
            if d.side is None:
                raise ValueError("PLACE_MARKET requiere side")
            try:
                resp = self.client.market_open(coin, d.side == Side.BUY, d.size or 0.0)
            except ValueError as e:
                self.store.record_risk_event(self.session_id, "orden_rechazada", str(e))
                return
            err = order_response_error(resp)
            if err:
                # El SDK devuelve rechazos (margen insuficiente, IOC sin cruce) como
                # statuses con 'error' SIN excepción: darlos por buenos mete el coin
                # en trend_open sin posición real y lo deja atascado toda la sesión.
                self.store.record_risk_event(
                    self.session_id, "orden_rechazada", f"market_open {coin}: {err}")
                return
            if not d.reduce_only:
                self.trend_open.add(coin)
            if self.state != SessionState.CLOSING:
                self.state = SessionState.ACTIVE
        elif d.action == ActionType.CLOSE:
            err = order_response_error(self.client.market_close(coin))
            if err:
                # rechazo sin excepción: dejar rastro; la posición sigue viva y la
                # reversión se reintenta en el siguiente tick
                self.store.record_risk_event(
                    self.session_id, "close_error", f"{coin}: {err}")
        elif d.action == ActionType.SET_STOP:
            if d.side is None or d.price is None:
                return
            if coin not in self.trend_open and abs(ms.inventory) <= 1e-12:
                return  # la entrada de este mismo tick falló: sin posición no hay stop
            closes = [c.close for c in ms.candles]
            highs = [c.high for c in ms.candles]
            lows = [c.low for c in ms.candles]
            atr_ = atr(highs, lows, closes, self.cfg.atr_period)[-1] if len(closes) > self.cfg.atr_period else 0.0
            # 0.35·ATR: con 0.1 el stop se recolocaba cada ~30s (365 veces en 3h
            # de tendencia en el soak 2) sin comprar protección real.
            thr = max(0.35 * atr_, 1e-9)
            cur = self.stop_levels.get(coin)
            is_long_stop = (d.side == Side.SELL)   # stop de venta protege un largo
            if cur is None:
                try:
                    res = self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0, reduce_only=True)
                    self.stop_levels[coin] = d.price
                    self.stop_oids[coin] = res.get("oid")
                except Exception as e:
                    self.store.record_risk_event(self.session_id, "stop_error", str(e))
                    return
            else:
                improves = (d.price > cur + thr) if is_long_stop else (d.price < cur - thr)
                if improves:
                    old = self.stop_oids.get(coin)
                    try:
                        if old is not None:
                            self.client.cancel_order(coin, old)
                        res = self.client.place_stop(coin, d.side == Side.BUY, d.price, d.size or 0.0, reduce_only=True)
                        self.stop_levels[coin] = d.price
                        self.stop_oids[coin] = res.get("oid")
                    except Exception as e:
                        self.store.record_risk_event(self.session_id, "stop_error", str(e))
                        return
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
                    # microestructura (None sin WS fresco) — la pinta el dashboard
                    "bbo": [ms.best_bid, ms.best_ask],
                    "microprice": ms.microprice,
                    "sigma": ms.sigma_px,
                    "flow_ratio": ms.flow_ratio,
                    "toxic": time.time() < self.toxic_until.get(coin, 0.0),
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
