"""Oscillator indicators — MACD, RSI, KDJ."""

from __future__ import annotations

import pandas as pd

from app.research.indicators.moving_average import ema


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD (Moving Average Convergence Divergence).

    Returns:
        (dif, dea, macd_hist) where macd_hist = 2 * (dif - dea).
    """
    ema_fast = ema(series, span=fast)
    ema_slow = ema(series, span=slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, span=signal)
    hist = 2.0 * (dif - dea)
    return dif, dea, hist


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100.0 - 100.0 / (1.0 + rs)


def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ indicator (stochastic oscillator variant used in A-share markets).

    Returns:
        (K, D, J)
    """
    lowest_low = low.rolling(window=n, min_periods=n).min()
    highest_high = high.rolling(window=n, min_periods=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, float("nan")) * 100.0

    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3.0 * k - 2.0 * d
    return k, d, j
