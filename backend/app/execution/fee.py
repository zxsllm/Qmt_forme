"""Fee calculator — A-share commission, stamp tax, transfer fee."""

from __future__ import annotations

from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.models import FeeConfig


def calc_fee(
    side: OrderSide,
    price: float,
    qty: int,
    ts_code: str,
    config: FeeConfig | None = None,
) -> float:
    """Return total fee for one fill.

    A-share rules:
    - Commission: max(amount * rate, min_commission), both sides
    - Stamp tax: amount * 0.05%, sell only
    - Transfer fee: amount * 0.001%, SSE only (code ends with .SH), both sides
    """
    cfg = config or FeeConfig()
    amount = price * qty

    commission = max(amount * cfg.commission_rate, cfg.min_commission)

    stamp = amount * cfg.stamp_tax_rate if side == OrderSide.SELL else 0.0

    transfer = 0.0
    if ts_code.endswith(".SH"):
        transfer = amount * cfg.transfer_fee_rate

    return round(commission + stamp + transfer, 2)
