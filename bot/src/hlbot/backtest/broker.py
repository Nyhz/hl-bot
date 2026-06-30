from __future__ import annotations
from hlbot.hl_client import round_price, round_size, meets_min_notional
import math

MAKER_FEE = 0.00015
TAKER_FEE = 0.00045


class BacktestBroker:
    """Cliente simulado: misma interfaz que HLClient pero rellena fills desde velas."""

    def __init__(self, capital: float, sz_decimals: dict[str, int]):
        self.cash = capital
        self.sz_decimals = sz_decimals
        self.positions: dict[str, dict] = {}      # coin -> {"size": float, "entry": float}
        self.resting: dict[str, list[dict]] = {}  # coin -> [order dicts]
        self.fills: list[dict] = []
        self.realized_total = 0.0
        self.fees_total = 0.0
        self.funding_total = 0.0
        self._price: dict[str, float] = {}
        self._ts = 0
        self._next_oid = 1000
        self._last_funding_hour = None

    # --- setters del runner ---
    def set_price(self, coin: str, px: float) -> None:
        self._price[coin] = px

    def set_ts(self, ts: int) -> None:
        self._ts = ts
        if self._last_funding_hour is None:
            self._last_funding_hour = ts // 3600

    # --- interfaz cliente ---
    def mid(self, coin: str) -> float:
        return self._price[coin]

    def set_leverage(self, coin, leverage, is_cross=False):
        return {"status": "ok"}

    def funding_rates(self) -> dict[str, float]:
        return {}

    def user_state(self) -> dict:
        aps = []
        unreal = 0.0
        for coin, p in self.positions.items():
            sz = p["size"]
            if sz == 0:
                continue
            mid = self._price.get(coin, p["entry"])
            u = (mid - p["entry"]) * sz
            unreal += u
            aps.append({"position": {
                "coin": coin, "szi": str(sz), "entryPx": str(p["entry"]),
                "positionValue": str(abs(sz) * mid), "unrealizedPnl": str(u),
                "leverage": {"value": 1}, "liquidationPx": None,
            }})
        return {"assetPositions": aps,
                "marginSummary": {"accountValue": str(self.cash + unreal)}}

    def open_orders(self, coin: str) -> list[dict]:
        return list(self.resting.get(coin, []))

    def _new_oid(self) -> int:
        self._next_oid += 1
        return self._next_oid

    def place_limit(self, coin, is_buy, price, size, post_only=True, reduce_only=False):
        szd = self.sz_decimals[coin]
        px = round_price(price, szd)
        sz = round_size(size, szd)
        if not reduce_only and not meets_min_notional(px, sz):
            scale = 10 ** szd
            sz = math.ceil((10.0 / px) * scale) / scale
        self.resting.setdefault(coin, []).append({
            "oid": self._new_oid(), "is_buy": is_buy, "limitPx": px, "sz": sz,
            "reduce_only": reduce_only, "is_trigger": False,
        })
        return {"status": "ok"}

    def place_stop(self, coin, is_buy, trigger_px, size, reduce_only=True):
        szd = self.sz_decimals[coin]
        oid = self._new_oid()
        self.resting.setdefault(coin, []).append({
            "oid": oid, "is_buy": is_buy, "limitPx": round_price(trigger_px, szd),
            "sz": round_size(size, szd), "reduce_only": reduce_only,
            "is_trigger": True, "triggerPx": round_price(trigger_px, szd),
        })
        return {"resp": {"status": "ok"}, "oid": oid}

    def cancel_all(self, coin: str) -> None:
        self.resting[coin] = []

    def cancel_order(self, coin: str, oid: int) -> None:
        self.resting[coin] = [o for o in self.resting.get(coin, []) if o["oid"] != oid]

    def market_open(self, coin, is_buy, size, slippage=0.01):
        self._apply_fill(coin, is_buy, self._price[coin], size, TAKER_FEE)
        return {"status": "ok"}

    def market_close(self, coin: str):
        p = self.positions.get(coin)
        if not p or p["size"] == 0:
            return {"status": "ok"}
        is_buy = p["size"] < 0          # cerrar un corto = comprar
        self._apply_fill(coin, is_buy, self._price[coin], abs(p["size"]), TAKER_FEE)
        return {"status": "ok"}

    # --- contabilidad ---
    def _apply_fill(self, coin, is_buy, price, size, fee_rate, reduce_only=False):
        fee = price * size * fee_rate
        self.cash -= fee
        self.fees_total += fee
        pos = self.positions.setdefault(coin, {"size": 0.0, "entry": 0.0})
        cur = pos["size"]
        signed = size if is_buy else -size
        closed_pnl = 0.0
        reducing = cur != 0 and (cur > 0) != (signed > 0)
        if reducing:
            closing = min(size, abs(cur))
            closed_pnl = ((price - pos["entry"]) * closing) if cur > 0 else ((pos["entry"] - price) * closing)
            self.cash += closed_pnl
            self.realized_total += closed_pnl
            new = cur + signed
            if abs(signed) <= abs(cur):
                pos["size"] = new
                if new == 0:
                    pos["entry"] = 0.0
            else:                       # cruza el cero -> nueva posición al otro lado
                pos["size"] = new
                pos["entry"] = price
        else:                           # abrir o añadir mismo lado
            total = abs(cur) + size
            pos["entry"] = (pos["entry"] * abs(cur) + price * size) / total if total else 0.0
            pos["size"] = cur + signed
        side = "Long" if (cur > 0 or (cur == 0 and is_buy)) else "Short"
        dir_ = ("Close " if reducing else "Open ") + side
        self.fills.append({
            "coin": coin, "dir": dir_, "price": price, "size": size,
            "fee": fee, "closed_pnl": closed_pnl, "ts": self._ts,
        })
        return closed_pnl

    def step(self, coin, candle, funding_rate):
        # 1) fills maker (órdenes no-trigger) al cruzar el rango de la vela
        still: list[dict] = []
        for o in self.resting.get(coin, []):
            if o["is_trigger"]:
                still.append(o); continue
            crossed = (candle.low <= o["limitPx"]) if o["is_buy"] else (candle.high >= o["limitPx"])
            if crossed:
                self._apply_fill(coin, o["is_buy"], o["limitPx"], o["sz"], MAKER_FEE,
                                 reduce_only=o["reduce_only"])
            else:
                still.append(o)
        self.resting[coin] = still
        # 2) stops (trigger) al cruzar triggerPx
        still2: list[dict] = []
        for o in self.resting.get(coin, []):
            if not o["is_trigger"]:
                still2.append(o); continue
            fired = (candle.low <= o["triggerPx"]) if not o["is_buy"] else (candle.high >= o["triggerPx"])
            if fired and self.positions.get(coin, {"size": 0})["size"] != 0:
                self._apply_fill(coin, o["is_buy"], o["triggerPx"],
                                 abs(self.positions[coin]["size"]), TAKER_FEE, reduce_only=True)
            else:
                still2.append(o)
        self.resting[coin] = still2
        # 3) funding horario sobre el notional de la posición
        ts = candle.t // 1000
        hour = ts // 3600
        if funding_rate is not None and self._last_funding_hour is not None and hour > self._last_funding_hour:
            p = self.positions.get(coin, {"size": 0.0, "entry": 0.0})
            if p["size"] != 0:
                notional = abs(p["size"]) * candle.close
                pay = funding_rate * notional * (1 if p["size"] > 0 else -1)  # largo paga si funding>0
                self.cash -= pay
                self.funding_total -= pay
        self._last_funding_hour = hour
        # 4) avanzar precio/ts
        self._price[coin] = candle.close
        self._ts = ts
