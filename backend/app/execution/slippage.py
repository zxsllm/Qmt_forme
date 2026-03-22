"""Slippage model — fixed tick + volume impact."""

from __future__ import annotations

from app.shared.interfaces.types import OrderSide


def calc_slippage(
    side: OrderSide,
    price: float,
    qty: int,
    bar_volume: float,
    *,
    tick_size: float = 0.01,
    base_ticks: int = 1,
    impact_threshold: float = 0.01,
    impact_factor: float = 0.002,
) -> float:
    """Return the slippage amount (always positive).

    Model:
    - Base: base_ticks * tick_size
    - Impact: if order_qty / bar_volume > threshold, add extra slippage
      proportional to the ratio excess.
    - Buy: price moves UP → slippage is positive
    - Sell: price moves DOWN → slippage is positive (adverse)
    """
    base = base_ticks * tick_size

    impact = 0.0
    if bar_volume > 0:
        ratio = qty / bar_volume
        if ratio > impact_threshold:
            impact = price * impact_factor * (ratio / impact_threshold)

    return round(base + impact, 4)


def apply_slippage(
    side: OrderSide,
    price: float,
    slippage: float,
) -> float:
    """Return fill price after applying slippage."""
    if side == OrderSide.BUY:
        return round(price + slippage, 2)
    return round(price - slippage, 2)
