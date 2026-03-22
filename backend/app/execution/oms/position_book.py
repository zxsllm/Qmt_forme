"""Position Book — tracks per-stock holdings and PnL."""

from __future__ import annotations

import logging

from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.models import Position

logger = logging.getLogger(__name__)


class PositionBook:
    """In-memory position ledger.

    Each stock has at most one Position entry (long only for A-share sim).
    """

    def __init__(self):
        self._positions: dict[str, Position] = {}

    def apply_fill(self, ts_code: str, side: OrderSide,
                   qty: int, price: float, fee: float) -> Position:
        """Update position after an order fill."""
        pos = self._positions.get(ts_code, Position(ts_code=ts_code))

        if side == OrderSide.BUY:
            total_cost = pos.avg_cost * pos.qty + price * qty + fee
            pos.qty += qty
            pos.avg_cost = total_cost / pos.qty if pos.qty else 0.0
        else:  # SELL
            if qty > pos.qty:
                raise ValueError(
                    f"cannot sell {qty} shares of {ts_code}, only hold {pos.qty}"
                )
            realized = (price - pos.avg_cost) * qty - fee
            pos.realized_pnl += realized
            pos.qty -= qty
            if pos.qty == 0:
                pos.avg_cost = 0.0

        pos.market_price = price
        pos.unrealized_pnl = (pos.market_price - pos.avg_cost) * pos.qty if pos.qty else 0.0

        self._positions[ts_code] = pos
        logger.info("position %s: qty=%d avg_cost=%.3f realized=%.2f",
                     ts_code, pos.qty, pos.avg_cost, pos.realized_pnl)
        return pos

    def update_market_price(self, ts_code: str, price: float) -> Position | None:
        """Refresh unrealized PnL with latest market price."""
        pos = self._positions.get(ts_code)
        if pos is None or pos.qty == 0:
            return pos
        pos.market_price = price
        pos.unrealized_pnl = (price - pos.avg_cost) * pos.qty
        return pos

    def get(self, ts_code: str) -> Position | None:
        return self._positions.get(ts_code)

    def get_all(self) -> list[Position]:
        return [p for p in self._positions.values() if p.qty > 0]

    def get_all_including_closed(self) -> list[Position]:
        return list(self._positions.values())

    def total_market_value(self) -> float:
        return sum(p.market_price * p.qty for p in self._positions.values() if p.qty > 0)

    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self._positions.values())
