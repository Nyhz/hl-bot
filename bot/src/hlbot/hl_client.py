from __future__ import annotations

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


from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account


class HLClient:
    def __init__(self, cfg: Config):
        base = constants.TESTNET_API_URL if cfg.testnet else constants.MAINNET_API_URL
        self.cfg = cfg
        self.address = cfg.account_address
        self.info = Info(base, skip_ws=True)
        meta = self.info.meta()
        self.sz_decimals = {a["name"]: a["szDecimals"] for a in meta["universe"]}
        self.exchange: Exchange | None = None
        if cfg.secret_key:
            wallet = Account.from_key(cfg.secret_key)
            self.exchange = Exchange(wallet, base, account_address=cfg.account_address)

    def mid(self, coin: str) -> float:
        return float(self.info.all_mids()[coin])

    def candles(self, coin: str, interval: str, start: int, end: int) -> list[dict]:
        return self.info.candles_snapshot(coin, interval, start, end)

    def user_state(self) -> dict:
        return self.info.user_state(self.address)

    def place_limit(self, coin: str, is_buy: bool, price: float, size: float,
                    post_only: bool = True, reduce_only: bool = False) -> dict:
        szd = self.sz_decimals[coin]
        px = round_price(price, szd)
        sz = round_size(size, szd)
        if not reduce_only and not meets_min_notional(px, sz):
            raise ValueError(f"orden por debajo del minimo de $10: {px}*{sz}")
        if self.exchange is None:
            raise RuntimeError("HLClient sin credenciales: no puede operar")
        tif = "Alo" if post_only else "Gtc"
        return self.exchange.order(coin, is_buy, sz, px, {"limit": {"tif": tif}},
                                   reduce_only=reduce_only)

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
