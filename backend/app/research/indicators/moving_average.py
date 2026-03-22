"""Moving average indicators — MA, EMA, WMA."""

from __future__ import annotations

import pandas as pd


def ma(series: pd.Series, window: int = 5) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int = 12) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def wma(series: pd.Series, window: int = 5) -> pd.Series:
    """Weighted Moving Average (linearly weighted)."""
    weights = pd.Series(range(1, window + 1), dtype=float)

    def _wma(x: pd.Series) -> float:
        return (x.values * weights.values).sum() / weights.sum()

    return series.rolling(window=window, min_periods=window).apply(_wma, raw=False)
