from __future__ import annotations
import numpy as np
import pandas as pd


def ema(values: list[float], period: int) -> list[float]:
    s = pd.Series(values, dtype="float64")
    return s.ewm(span=period, adjust=False).mean().tolist()


def _true_range(high, low, close) -> pd.Series:
    h = pd.Series(high, dtype="float64")
    l = pd.Series(low, dtype="float64")
    c = pd.Series(close, dtype="float64")
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr


def atr(high, low, close, period: int = 14) -> list[float]:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False).mean().tolist()


def adx(high, low, close, period: int = 14) -> list[float]:
    h = pd.Series(high, dtype="float64")
    l = pd.Series(low, dtype="float64")
    up = h.diff()
    down = -l.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = _true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    adx_ = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx_.fillna(0.0).tolist()
