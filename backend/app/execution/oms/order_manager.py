"""Order Manager — order lifecycle state machine with idempotency."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.shared.interfaces.types import OrderSide, OrderStatus, OrderType
from app.shared.interfaces.models import Order, OrderRequest, Signal

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
    },
    OrderStatus.PARTIAL_FILLED: {
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELED: set(),
    OrderStatus.REJECTED: set(),
}


class OrderManager:
    """In-memory order book with signal dedup and state machine enforcement.

    Persistence to DB (SimOrder) is handled by the caller / service layer.
    """

    def __init__(self, *, dedup_window_minutes: int = 5):
        self._orders: dict[UUID, Order] = {}
        self._signal_index: dict[UUID, UUID] = {}  # signal_id → order_id
        self._dedup_window = timedelta(minutes=dedup_window_minutes)
        self._recent_signals: dict[str, datetime] = {}  # "ts_code|side" → ts

    def signal_to_request(self, signal: Signal) -> OrderRequest | None:
        """Convert a Signal into an OrderRequest, applying dedup rules.

        Returns None if the signal is a duplicate.
        """
        if signal.signal_id in self._signal_index:
            logger.info("signal %s already submitted, skipping", signal.signal_id)
            return None

        key = f"{signal.ts_code}|{signal.side.value}"
        last = self._recent_signals.get(key)
        if last and (signal.timestamp - last) < self._dedup_window:
            logger.info("duplicate direction signal for %s within window", key)
            return None

        self._recent_signals[key] = signal.timestamp

        req = OrderRequest(
            order_id=uuid4(),
            signal_id=signal.signal_id,
            ts_code=signal.ts_code,
            side=signal.side,
            order_type=signal.order_type,
            price=signal.price,
            qty=signal.qty,
            created_at=signal.timestamp,
        )
        return req

    def submit(self, req: OrderRequest) -> Order:
        """Create a new order from a validated request."""
        order = Order(
            order_id=req.order_id,
            signal_id=req.signal_id,
            ts_code=req.ts_code,
            side=req.side,
            order_type=req.order_type,
            price=req.price,
            qty=req.qty,
            status=OrderStatus.SUBMITTED,
            created_at=req.created_at,
            updated_at=datetime.now(),
        )
        self._orders[order.order_id] = order
        self._signal_index[order.signal_id] = order.order_id
        logger.info("order %s submitted: %s %s %d@%s",
                     order.order_id, order.side.value, order.ts_code,
                     order.qty, order.price or "MARKET")
        return order

    def transition(self, order_id: UUID, new_status: OrderStatus,
                   *, filled_qty: int = 0, filled_price: float = 0.0,
                   fee: float = 0.0, slippage: float = 0.0,
                   reject_reason: str = "") -> Order:
        """Move an order to a new status with validation."""
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"order {order_id} not found")

        if new_status not in _VALID_TRANSITIONS[order.status]:
            raise ValueError(
                f"invalid transition {order.status.value} → {new_status.value} "
                f"for order {order_id}"
            )

        order.status = new_status
        order.updated_at = datetime.now()

        if filled_qty:
            order.filled_qty += filled_qty
            total_cost = order.filled_price * (order.filled_qty - filled_qty) + filled_price * filled_qty
            order.filled_price = total_cost / order.filled_qty if order.filled_qty else 0.0
        if fee:
            order.fee += fee
        if slippage:
            order.slippage += slippage
        if reject_reason:
            order.reject_reason = reject_reason

        logger.info("order %s → %s (filled %d/%d)",
                     order_id, new_status.value, order.filled_qty, order.qty)
        return order

    def cancel(self, order_id: UUID) -> Order:
        """Cancel a pending or submitted order."""
        return self.transition(order_id, OrderStatus.CANCELED)

    def get(self, order_id: UUID) -> Order | None:
        return self._orders.get(order_id)

    def get_open_orders(self) -> list[Order]:
        return [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED)
        ]

    def get_all_orders(self) -> list[Order]:
        return list(self._orders.values())
