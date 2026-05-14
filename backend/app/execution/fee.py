"""Fee calculator — A-share + 可转债 (CB) commission, stamp tax, transfer fee."""

from __future__ import annotations

from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.models import FeeConfig
from app.shared.data.data_loader import is_cb_code


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
    - Transfer fee: amount * 0.001%, SSE only (.SH), both sides

    可转债 (CB, 11*.SH / 12*.SZ) rules:
    - Commission: max(amount * rate, min_commission), both sides (broker rate same)
    - Stamp tax: NONE (exempt by regulation)
    - Transfer fee: NONE (exempt)
    """
    cfg = config or FeeConfig()
    amount = price * qty

    commission = max(amount * cfg.commission_rate, cfg.min_commission)

    if is_cb_code(ts_code):
        # CB: no stamp tax, no transfer fee
        return round(commission, 2)

    stamp = amount * cfg.stamp_tax_rate if side == OrderSide.SELL else 0.0

    transfer = 0.0
    if ts_code.endswith(".SH"):
        transfer = amount * cfg.transfer_fee_rate

    return round(commission + stamp + transfer, 2)
