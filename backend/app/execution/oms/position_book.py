"""Position Book — multi-lot ledger with T+1/T+0 settlement and auto-close support.

Each BUY fill creates a new lot (unique lot_id). SELL fills either match a target
lot (auto_close path) or consume lots FIFO by entry_date (manual SELL path).

Aggregate views (for risk checks / API display) sum across lots per ts_code.
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from uuid import uuid4

from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.models import Position

logger = logging.getLogger(__name__)


class PositionBook:
    """In-memory multi-lot position ledger.

    Per-lot model:
    - BUY fill: append a new Position (lot) with unique lot_id and sell_anchor metadata
    - SELL fill (with target_lot_id): decrement that specific lot
    - SELL fill (without lot_id): FIFO consume lots by entry_date
    - T+1: lot.available_qty unchanged until next begin_day()
    - T+0 (CB): lot.available_qty += qty immediately at BUY fill

    External callers see aggregate Position via get() / get_all() for backward
    compatibility (qty summed, avg_cost weighted, sell_anchor blank since multi).
    """

    def __init__(self):
        # ts_code → list of lots (chronological by entry order)
        self._lots: dict[str, list[Position]] = {}

    # ------------------------------------------------------------------
    # Day lifecycle
    # ------------------------------------------------------------------

    def begin_day(self) -> None:
        """Unlock T+1 lots; T+0 lots are unlocked already at fill time."""
        unlocked = 0
        for lots in self._lots.values():
            for lot in lots:
                if lot.qty > 0 and lot.settlement_rule == "T+1":
                    if lot.available_qty < lot.qty:
                        lot.available_qty = lot.qty
                        unlocked += 1
        logger.info("T+1 unlock: %d lots", unlocked)

    # ------------------------------------------------------------------
    # Fill application
    # ------------------------------------------------------------------

    def apply_fill(
        self,
        ts_code: str,
        side: OrderSide,
        qty: int,
        price: float,
        fee: float,
        *,
        lot_id: str | None = None,
        sell_anchor: str = "",
        sell_anchor_date: str = "",
        sell_anchor_time: str = "",
        sell_reason: str = "",
        pick_role: str = "",
        pick_kind: str = "stock",
        underlying_code: str | None = None,
        settlement_rule: str = "T+1",
        entry_date: str = "",
    ) -> Position:
        """Apply a single fill to the book.

        BUY: appends a new lot. lot_id is generated if not given.
        SELL: matches target lot if lot_id given (auto_close), else FIFO consumes lots.

        Returns the lot that was modified (BUY: new lot; SELL: most-recently-touched).
        """
        lots = self._lots.setdefault(ts_code, [])

        if side == OrderSide.BUY:
            new_lot = Position(
                ts_code=ts_code,
                qty=qty,
                # T+0: immediately sellable; T+1: locked until begin_day()
                available_qty=qty if settlement_rule == "T+0" else 0,
                avg_cost=(price * qty + fee) / qty if qty else 0.0,
                market_price=price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                lot_id=lot_id or str(uuid4()),
                sell_anchor=sell_anchor,
                sell_anchor_date=sell_anchor_date,
                sell_anchor_time=sell_anchor_time,
                sell_reason=sell_reason,
                pick_role=pick_role,
                pick_kind=pick_kind,
                underlying_code=underlying_code,
                settlement_rule=settlement_rule,
                entry_date=entry_date or datetime.now().strftime("%Y-%m-%d"),
                pending_sell_qty=0,
            )
            lots.append(new_lot)
            logger.info("BUY lot %s %s qty=%d @ %.3f (anchor=%s rule=%s)",
                         new_lot.lot_id[:8], ts_code, qty, price,
                         sell_anchor or "-", settlement_rule)
            return new_lot

        # ---- SELL path ----
        remaining = qty
        target_lot: Position | None = None
        if lot_id:
            target_lot = next((lot for lot in lots if lot.lot_id == lot_id), None)
            if target_lot is None:
                raise ValueError(f"SELL: lot_id {lot_id} not found for {ts_code}")
            order = [target_lot]
        else:
            # FIFO by entry_date (earliest first)
            order = sorted(
                [lot for lot in lots if lot.qty > 0],
                key=lambda x: x.entry_date,
            )

        last_touched: Position | None = None
        for lot in order:
            if remaining <= 0:
                break
            if lot.qty <= 0:
                continue
            if lot.available_qty <= 0:
                raise ValueError(
                    f"T+1: lot {lot.lot_id[:8]} {ts_code} qty={lot.qty} not available today"
                )
            sell_qty = min(remaining, lot.available_qty)
            realized = (price - lot.avg_cost) * sell_qty - fee * (sell_qty / qty if qty else 0)
            lot.realized_pnl += realized
            lot.qty -= sell_qty
            lot.available_qty -= sell_qty
            lot.pending_sell_qty = max(0, lot.pending_sell_qty - sell_qty)
            lot.market_price = price
            lot.unrealized_pnl = (lot.market_price - lot.avg_cost) * lot.qty if lot.qty else 0.0
            remaining -= sell_qty
            last_touched = lot
            logger.info("SELL lot %s %s sell_qty=%d @ %.3f remaining=%d",
                         lot.lot_id[:8], ts_code, sell_qty, price, lot.qty)

        if remaining > 0:
            raise ValueError(
                f"SELL: cannot fill {qty} of {ts_code}, "
                f"only {qty - remaining} available across lots"
            )

        # Garbage-collect fully-sold lots (keep last for realized_pnl tracking via aggregation)
        # Actually we keep them so realized_pnl history is preserved on aggregate get_all_including_closed.

        return last_touched  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Mark price (broadcast to all lots of a ts_code)
    # ------------------------------------------------------------------

    def update_market_price(self, ts_code: str, price: float) -> None:
        lots = self._lots.get(ts_code)
        if not lots:
            return
        for lot in lots:
            if lot.qty > 0:
                lot.market_price = price
                lot.unrealized_pnl = (price - lot.avg_cost) * lot.qty

    # ------------------------------------------------------------------
    # Auto-close discovery
    # ------------------------------------------------------------------

    def iter_lots_due_for_close(self, now_dt: datetime) -> list[Position]:
        """Return lots whose sell_anchor has triggered at now_dt.

        Skips lots with pending_sell_qty > 0 (already-submitted SELL not yet filled).
        """
        today = now_dt.strftime("%Y-%m-%d")
        hhmm = now_dt.strftime("%H%M")
        sec = now_dt.second
        due: list[Position] = []
        for lots in self._lots.values():
            for lot in lots:
                if lot.qty <= 0:
                    continue
                if lot.pending_sell_qty >= lot.qty:
                    continue
                anchor = lot.sell_anchor
                if not anchor:
                    continue
                if anchor == "next_open":
                    if lot.sell_anchor_date and lot.sell_anchor_date <= today:
                        due.append(lot)
                elif anchor == "intraday_at":
                    if not lot.sell_anchor_time:
                        continue
                    # Tail-aligned: trigger only in last 5s of target minute [F10]
                    target_hhmm = lot.sell_anchor_time[:4]
                    if hhmm == target_hhmm and sec >= 55:
                        due.append(lot)
                    elif hhmm > target_hhmm:
                        # Missed window — still need to close; fire at first chance
                        due.append(lot)
                elif anchor == "today_close":
                    if hhmm >= "1455" and (hhmm > "1455" or sec >= 55):
                        due.append(lot)
        return due

    # ------------------------------------------------------------------
    # Aggregate views (backward-compatible API)
    # ------------------------------------------------------------------

    def get(self, ts_code: str) -> Position | None:
        """Return aggregated Position across all lots of ts_code (qty sum, weighted cost)."""
        lots = self._lots.get(ts_code)
        if not lots:
            return None
        active = [lot for lot in lots if lot.qty > 0]
        if not active:
            return None
        total_qty = sum(lot.qty for lot in active)
        total_avail = sum(lot.available_qty for lot in active)
        total_cost = sum(lot.avg_cost * lot.qty for lot in active)
        total_unrealized = sum(lot.unrealized_pnl for lot in lots)
        total_realized = sum(lot.realized_pnl for lot in lots)
        avg_cost = total_cost / total_qty if total_qty else 0.0
        market_price = active[-1].market_price
        return Position(
            ts_code=ts_code,
            qty=total_qty,
            available_qty=total_avail,
            avg_cost=avg_cost,
            market_price=market_price,
            unrealized_pnl=total_unrealized,
            realized_pnl=total_realized,
        )

    def get_all(self) -> list[Position]:
        """All ts_codes with active qty, aggregated."""
        out = []
        for ts in self._lots.keys():
            agg = self.get(ts)
            if agg and agg.qty > 0:
                out.append(agg)
        return out

    def get_all_lots(self) -> list[Position]:
        """All lots (active + closed) — for persistence."""
        out = []
        for lots in self._lots.values():
            out.extend(lots)
        return out

    def get_all_including_closed(self) -> list[Position]:
        return self.get_all_lots()

    def get_active_lots(self, ts_code: str) -> list[Position]:
        """Active lots for a specific ts_code (qty > 0)."""
        return [lot for lot in self._lots.get(ts_code, []) if lot.qty > 0]

    def get_active_lot_count(self, ts_code: str) -> int:
        """For Pattern rebuy guard: don't rebuy while a previous lot is still active."""
        return sum(1 for lot in self._lots.get(ts_code, []) if lot.qty > 0)

    def total_market_value(self) -> float:
        return sum(
            lot.market_price * lot.qty
            for lots in self._lots.values()
            for lot in lots
            if lot.qty > 0
        )

    def total_unrealized_pnl(self) -> float:
        return sum(
            lot.unrealized_pnl
            for lots in self._lots.values()
            for lot in lots
        )

    def total_realized_pnl(self) -> float:
        return sum(
            lot.realized_pnl
            for lots in self._lots.values()
            for lot in lots
        )
