"""Simulated matching engine — fills orders against minute bars."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.shared.interfaces.types import OrderSide, OrderStatus, OrderType
from app.shared.interfaces.models import BarData, FeeConfig, Order
from app.execution.fee import calc_fee
from app.execution.slippage import calc_slippage, apply_slippage

logger = logging.getLogger(__name__)


@dataclass
class FillResult:
    order_id: UUID
    fill_price: float
    fill_qty: int
    fee: float
    slippage: float
    fully_filled: bool


class SimMatcher:
    """Match pending orders against the next bar (simulating real execution).

    Rules:
    - MARKET orders fill at next bar's open price + slippage.
    - LIMIT BUY fills if bar.low <= limit_price (at min(open, limit)).
    - LIMIT SELL fills if bar.high >= limit_price (at max(open, limit)).
    - Volume cap: single fill <= 20% of bar volume.
    """

    MAX_VOLUME_PCT = 0.20

    def __init__(self, fee_config: FeeConfig | None = None):
        self.fee_config = fee_config or FeeConfig()

    def try_fill(self, order: Order, bar: BarData) -> FillResult | None:
        """Attempt to fill an order against a single bar.

        Returns FillResult if (partially) filled, None if not triggered.
        """
        if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED):
            return None

        remaining = order.qty - order.filled_qty
        if remaining <= 0:
            return None

        max_qty = int(bar.vol * self.MAX_VOLUME_PCT) if bar.vol > 0 else remaining
        max_qty = max(max_qty, 100)
        fill_qty = min(remaining, max_qty)

        base_price = self._determine_price(order, bar)
        if base_price is None:
            return None

        slip = calc_slippage(order.side, base_price, fill_qty, bar.vol)
        fill_price = apply_slippage(order.side, base_price, slip)

        fee = calc_fee(order.side, fill_price, fill_qty, order.ts_code, self.fee_config)

        fully = fill_qty >= remaining

        logger.info(
            "fill %s %s %s: %d@%.2f (slip=%.4f fee=%.2f) %s",
            order.order_id, order.side.value, order.ts_code,
            fill_qty, fill_price, slip, fee,
            "FULL" if fully else "PARTIAL",
        )

        return FillResult(
            order_id=order.order_id,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee=fee,
            slippage=slip,
            fully_filled=fully,
        )

    @staticmethod
    def _determine_price(order: Order, bar: BarData) -> float | None:
        if order.order_type == OrderType.MARKET:
            return bar.open

        assert order.price is not None
        if order.side == OrderSide.BUY:
            if bar.low <= order.price:
                return min(bar.open, order.price)
            return None
        else:
            if bar.high >= order.price:
                return max(bar.open, order.price)
            return None
