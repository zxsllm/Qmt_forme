"""Simulated matching engine — fills orders against minute bars.

Enforces A-share market rules:
- 涨停板: BUY orders blocked if bar.low >= up_limit
- 跌停板: SELL orders blocked if bar.high <= down_limit
- 一字板: all orders blocked if open == high == low == close at limit
- Volume cap: single fill <= 20% of bar volume
"""

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
    - Price limits: enforces 涨停/跌停/一字板 rules when limits are provided.
    """

    MAX_VOLUME_PCT = 0.20

    def __init__(self, fee_config: FeeConfig | None = None):
        self.fee_config = fee_config or FeeConfig()

    def try_fill(
        self,
        order: Order,
        bar: BarData,
        up_limit: float | None = None,
        down_limit: float | None = None,
    ) -> FillResult | None:
        """Attempt to fill an order against a single bar.

        Returns FillResult if (partially) filled, None if not triggered.
        """
        if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED):
            return None

        remaining = order.qty - order.filled_qty
        if remaining <= 0:
            return None

        # --- A-share market rules ---
        if not self._is_tradable(order, bar, up_limit, down_limit):
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
    def _is_tradable(
        order: Order,
        bar: BarData,
        up_limit: float | None,
        down_limit: float | None,
    ) -> bool:
        """Check A-share tradability rules against the bar."""
        if up_limit and down_limit:
            is_one_board = (
                abs(bar.high - bar.low) < 0.01
                and (bar.close >= up_limit or bar.close <= down_limit)
            )
            if is_one_board:
                logger.debug("一字板 %s, skipping", order.ts_code)
                return False

        if order.side == OrderSide.BUY and up_limit:
            if bar.low >= up_limit:
                logger.debug("涨停 %s (low=%.2f >= limit=%.2f), buy blocked",
                             order.ts_code, bar.low, up_limit)
                return False

        if order.side == OrderSide.SELL and down_limit:
            if bar.high <= down_limit:
                logger.debug("跌停 %s (high=%.2f <= limit=%.2f), sell blocked",
                             order.ts_code, bar.high, down_limit)
                return False

        return True

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
