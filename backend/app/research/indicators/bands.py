"""Band indicators — Bollinger Bands."""

from __future__ import annotations

import pandas as pd

from app.research.indicators.moving_average import ma


def boll(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns:
        (mid, upper, lower) where mid = MA, upper/lower = mid +/- num_std * std.
    """
    mid = ma(series, window=window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower
