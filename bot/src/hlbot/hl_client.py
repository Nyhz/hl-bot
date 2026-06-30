from __future__ import annotations

import math
from decimal import Decimal

from hlbot.config import Config


def round_size(size: float, sz_decimals: int) -> float:
    return round(size, sz_decimals)


def round_price(price: float, sz_decimals: int, max_decimals: int = 6) -> float:
    # Hyperliquid perps: max 5 cifras significativas Y max (max_decimals - sz_decimals) decimales.
    # Los decimales efectivos = min de ambas restricciones.
    if price == 0:
        return 0.0
    d = Decimal(repr(price))
    sig = d.adjusted()              # exponente de la cifra más significativa
    places_for_sig = 4 - sig       # 5 cifras significativas
    max_dec = max_decimals - sz_decimals
    decimals = min(max_dec, max(0, places_for_sig))
    return round(price, decimals)


def meets_min_notional(price: float, size: float, min_notional: float = 10.0) -> bool:
    return price * size >= min_notional


def stop_order_type(trigger_px: float) -> dict:
    # Orden trigger stop-loss de mercado (cierra la posición al cruzar triggerPx).
    return {"trigger": {"isMarket": True, "triggerPx": trigger_px, "tpsl": "sl"}}


from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account


# Timeout (segundos) de cada llamada HTTP al SDK de HL. Acota toda llamada de red para que
# una respuesta colgada no retenga el lock del engine indefinidamente (un kill podría esperar).
HTTP_TIMEOUT = 10


class HLClient:
    def __init__(self, cfg: Config):
        base = constants.TESTNET_API_URL if cfg.testnet else constants.MAINNET_API_URL
        self.cfg = cfg
        self.address = cfg.account_address
        self.info = Info(base, skip_ws=True)
        self.info.timeout = HTTP_TIMEOUT       # el SDK usa session.post(..., timeout=self.timeout)
        meta = self.info.meta()
        self.sz_decimals = {a["name"]: a["szDecimals"] for a in meta["universe"]}
        self.exchange: Exchange | None = None
        if cfg.secret_key:
            wallet = Account.from_key(cfg.secret_key)
            self.exchange = Exchange(wallet, base, account_address=cfg.account_address)
            self.exchange.timeout = HTTP_TIMEOUT

    def mid(self, coin: str) -> float:
        return float(self.info.all_mids()[coin])

    def candles(self, coin: str, interval: str, start: int, end: int) -> list[dict]:
        return self.info.candles_snapshot(coin, interval, start, end)

    def funding_rates(self) -> dict[str, float]:
        # Funding horario actual por activo (metaAndAssetCtxs trae 'funding' por moneda).
        meta, ctxs = self.info.meta_and_asset_ctxs()
        out: dict[str, float] = {}
        for a, c in zip(meta.get("universe", []), ctxs):
            f = c.get("funding")
            if f is not None:
                out[a["name"]] = float(f)
        return out

    def user_state(self) -> dict:
        return self.info.user_state(self.address)

    def place_limit(self, coin: str, is_buy: bool, price: float, size: float,
                    post_only: bool = True, reduce_only: bool = False) -> dict:
        szd = self.sz_decimals[coin]
        px = round_price(price, szd)
        sz = round_size(size, szd)
        # La posicion objetivo es ~$10 (el minimo de HL), sin colchon: si el redondeo de
        # tamano deja la orden por debajo del minimo, subimos el tamano al siguiente tick.
        if not reduce_only and not meets_min_notional(px, sz):
            scale = 10 ** szd
            sz = math.ceil((10.0 / px) * scale) / scale
        if not reduce_only and not meets_min_notional(px, sz):
            raise ValueError(f"orden por debajo del minimo de $10: {px}*{sz}")
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        tif = "Alo" if post_only else "Gtc"
        return self.exchange.order(coin, is_buy, sz, px, {"limit": {"tif": tif}},
                                   reduce_only=reduce_only)

    def set_leverage(self, coin: str, leverage: int, is_cross: bool = False) -> dict:
        # Fija el apalancamiento máximo por activo (isolated por defecto) para acotar
        # el riesgo de liquidación de cada posición.
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        return self.exchange.update_leverage(leverage, coin, is_cross)

    def market_open(self, coin: str, is_buy: bool, size: float,
                    slippage: float = 0.01) -> dict:
        # Entrada de mercado REAL (IOC a precio cruzado con slippage), no un límite al mid
        # que se puede quedar en reposo.
        szd = self.sz_decimals[coin]
        sz = round_size(size, szd)
        mid = self.mid(coin)
        if not meets_min_notional(mid, sz):
            scale = 10 ** szd
            sz = math.ceil((10.0 / mid) * scale) / scale
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        return self.exchange.market_open(coin, is_buy, sz, None, slippage)

    def market_close(self, coin: str) -> dict:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        return self.exchange.market_close(coin)

    def cancel_all(self, coin: str) -> None:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        for o in self.info.open_orders(self.address):
            if o["coin"] == coin:
                self.exchange.cancel(coin, o["oid"])

    def cancel_order(self, coin: str, oid: int) -> None:
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        self.exchange.cancel(coin, oid)

    def open_orders(self, coin: str) -> list[dict]:
        return [o for o in self.info.open_orders(self.address) if o.get("coin") == coin]

    def place_stop(self, coin: str, is_buy: bool, trigger_px: float, size: float,
                   reduce_only: bool = True, slippage: float = 0.005) -> dict:
        szd = self.sz_decimals[coin]
        trig = round_price(trigger_px, szd)
        # limit_px agresivo más allá del trigger para asegurar la ejecución del trigger de mercado:
        # un stop que COMPRA (cierra un corto) acepta pagar más; uno que VENDE acepta cobrar menos.
        limit = trigger_px * (1 + slippage) if is_buy else trigger_px * (1 - slippage)
        limit = round_price(limit, szd)
        sz = round_size(size, szd)
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        resp = self.exchange.order(coin, is_buy, sz, limit, stop_order_type(trig),
                                   reduce_only=reduce_only)
        try:
            st = resp["response"]["data"]["statuses"][0]
            oid = (st.get("resting") or st.get("filled") or {}).get("oid")
        except (KeyError, IndexError, TypeError):
            oid = None
        return {"resp": resp, "oid": oid}

    def user_fills(self) -> list[dict]:
        return self.info.user_fills(self.address)

    def user_funding(self, start_ms: int) -> list[dict]:
        return self.info.user_funding_history(self.address, start_ms)
