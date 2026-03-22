"""Position Book — tracks per-stock holdings with T+1 settlement."""

from __future__ import annotations

import logging

from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.models import Position

logger = logging.getLogger(__name__)


class PositionBook:
    """In-memory position ledger (long only, A-share T+1).

    T+1 rule: shares bought today cannot be sold until the next trading day.
    - `qty`: total shares held
    - `available_qty`: shares that can be sold today
    - BUY fill: qty increases, available_qty unchanged (locked until tomorrow)
    - SELL fill: both qty and available_qty decrease
    - begin_day(): sets available_qty = qty (unlock yesterday's buys)
    """

    def __init__(self):
        self._positions: dict[str, Position] = {}

    def begin_day(self) -> None:
        """Unlock all positions for selling (T+1 settlement)."""
        for pos in self._positions.values():
            if pos.qty > 0:
                pos.available_qty = pos.qty
        logger.info("T+1 unlock: %d positions available for trading",
                     sum(1 for p in self._positions.values() if p.available_qty > 0))

    def apply_fill(self, ts_code: str, side: OrderSide,
                   qty: int, price: float, fee: float) -> Position:
        """Update position after an order fill."""
        pos = self._positions.get(ts_code, Position(ts_code=ts_code))

        if side == OrderSide.BUY:
            total_cost = pos.avg_cost * pos.qty + price * qty + fee
            pos.qty += qty
            # T+1: newly bought shares are NOT available for selling today
            pos.avg_cost = total_cost / pos.qty if pos.qty else 0.0
        else:  # SELL
            if qty > pos.available_qty:
                raise ValueError(
                    f"T+1: cannot sell {qty} of {ts_code}, "
                    f"only {pos.available_qty} available (total: {pos.qty})"
                )
            realized = (price - pos.avg_cost) * qty - fee
            pos.realized_pnl += realized
            pos.qty -= qty
            pos.available_qty -= qty
            if pos.qty == 0:
                pos.avg_cost = 0.0

        pos.market_price = price
        pos.unrealized_pnl = (pos.market_price - pos.avg_cost) * pos.qty if pos.qty else 0.0

        self._positions[ts_code] = pos
        logger.info("position %s: qty=%d avail=%d avg_cost=%.3f",
                     ts_code, pos.qty, pos.available_qty, pos.avg_cost)
        return pos

    def update_market_price(self, ts_code: str, price: float) -> Position | None:
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
