"""Persistence layer — bridges in-memory OMS state to sim_* DB tables.

Write operations are designed to be called via asyncio.create_task() from
synchronous TradingEngine methods, so they never block the main trading flow.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import async_session
from app.shared.models.stock import SimOrder, SimPosition, SimAccount
from app.shared.interfaces.types import OrderSide, OrderStatus, OrderType
from app.shared.interfaces.models import Account, Order, Position

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic ↔ ORM row conversion
# ---------------------------------------------------------------------------

def _order_to_row(o: Order, *, signal_extras: dict | None = None) -> dict:
    """Convert Order → DB row. signal_extras carries pattern-aware fields
    (sell_anchor / pick_kind / etc.) since they live on Signal, not Order."""
    extras = signal_extras or {}
    return {
        "order_id": str(o.order_id),
        "signal_id": str(o.signal_id),
        "ts_code": o.ts_code,
        "side": o.side.value,
        "order_type": o.order_type.value,
        "price": o.price,
        "qty": o.qty,
        "filled_qty": o.filled_qty,
        "filled_price": o.filled_price,
        "status": o.status.value,
        "fee": o.fee,
        "slippage": o.slippage,
        "reject_reason": o.reject_reason,
        "sell_anchor": extras.get("sell_anchor", ""),
        "sell_anchor_time": extras.get("sell_anchor_time"),
        "sell_reason": extras.get("sell_reason", ""),
        "pick_kind": extras.get("pick_kind", "stock"),
        "pick_role": extras.get("pick_role", ""),
        "buy_anchor": extras.get("buy_anchor", "market"),
        "buy_anchor_time": extras.get("buy_anchor_time"),
        "underlying_code": extras.get("underlying_code"),
        "lot_id": extras.get("lot_id", ""),
        "extra": extras.get("extra", {}),
        "created_at": o.created_at,
        "updated_at": o.updated_at,
    }


def _row_to_order(row: SimOrder) -> Order:
    return Order(
        order_id=UUID(row.order_id),
        signal_id=UUID(row.signal_id),
        ts_code=row.ts_code,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        price=row.price,
        qty=row.qty,
        filled_qty=row.filled_qty,
        filled_price=row.filled_price,
        status=OrderStatus(row.status),
        fee=row.fee,
        slippage=row.slippage,
        reject_reason=row.reject_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _position_to_row(p: Position) -> dict:
    return {
        "lot_id": p.lot_id or p.ts_code,  # legacy fallback
        "ts_code": p.ts_code,
        "qty": p.qty,
        "available_qty": p.available_qty,
        "avg_cost": p.avg_cost,
        "market_price": p.market_price,
        "unrealized_pnl": p.unrealized_pnl,
        "realized_pnl": p.realized_pnl,
        "sell_anchor": p.sell_anchor,
        "sell_anchor_date": p.sell_anchor_date,
        "sell_anchor_time": p.sell_anchor_time,
        "sell_reason": p.sell_reason,
        "pick_role": p.pick_role,
        "pick_kind": p.pick_kind,
        "underlying_code": p.underlying_code,
        "settlement_rule": p.settlement_rule,
        "entry_date": p.entry_date,
        "pending_sell_qty": p.pending_sell_qty,
    }


def _row_to_position(row: SimPosition) -> Position:
    return Position(
        ts_code=row.ts_code,
        qty=row.qty,
        available_qty=row.available_qty,
        avg_cost=row.avg_cost,
        market_price=row.market_price,
        unrealized_pnl=row.unrealized_pnl,
        realized_pnl=row.realized_pnl,
        lot_id=row.lot_id,
        sell_anchor=row.sell_anchor,
        sell_anchor_date=row.sell_anchor_date,
        sell_anchor_time=row.sell_anchor_time,
        sell_reason=row.sell_reason,
        pick_role=row.pick_role,
        pick_kind=row.pick_kind,
        underlying_code=row.underlying_code,
        settlement_rule=row.settlement_rule,
        entry_date=row.entry_date,
        pending_sell_qty=row.pending_sell_qty,
    )


def _account_to_row(a: Account) -> dict:
    return {
        "id": 1,
        "total_asset": a.total_asset,
        "cash": a.cash,
        "frozen": a.frozen,
        "market_value": a.market_value,
        "total_pnl": a.total_pnl,
        "today_pnl": a.today_pnl,
    }


def _row_to_account(row: SimAccount) -> Account:
    return Account(
        total_asset=row.total_asset,
        cash=row.cash,
        frozen=row.frozen,
        market_value=row.market_value,
        total_pnl=row.total_pnl,
        today_pnl=row.today_pnl,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Batch write (single transaction)
# ---------------------------------------------------------------------------

async def save_batch(
    orders: list[Order] | None = None,
    positions: list[Position] | None = None,
    account: Account | None = None,
    order_extras: dict[str, dict] | None = None,
) -> None:
    """Persist orders/positions/account in one transaction (non-blocking).

    order_extras: optional {order_id_str → {sell_anchor, pick_kind, ...}} to attach
    pattern-aware fields to SimOrder rows (these live on the Signal, not Order).
    """
    try:
        async with async_session() as session:
            if orders:
                for o in orders:
                    extras = (order_extras or {}).get(str(o.order_id))
                    row = _order_to_row(o, signal_extras=extras)
                    stmt = pg_insert(SimOrder).values(**row).on_conflict_do_update(
                        index_elements=["order_id"],
                        set_={k: v for k, v in row.items() if k != "order_id"},
                    )
                    await session.execute(stmt)
            if positions:
                for p in positions:
                    row = _position_to_row(p)
                    stmt = pg_insert(SimPosition).values(**row).on_conflict_do_update(
                        index_elements=["lot_id"],
                        set_={k: v for k, v in row.items() if k != "lot_id"},
                    )
                    await session.execute(stmt)
            if account:
                row = _account_to_row(account)
                stmt = pg_insert(SimAccount).values(**row).on_conflict_do_update(
                    index_elements=["id"],
                    set_={k: v for k, v in row.items() if k != "id"},
                )
                await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.exception("failed to persist OMS batch")


# ---------------------------------------------------------------------------
# Load (startup recovery)
# ---------------------------------------------------------------------------

async def load_all_state() -> tuple[list[Order], list[Position], Account | None]:
    """Read all persisted OMS state from DB for startup recovery."""
    async with async_session() as session:
        result = await session.execute(select(SimOrder))
        orders = [_row_to_order(r) for r in result.scalars().all()]

        result = await session.execute(select(SimPosition))
        positions = [_row_to_position(r) for r in result.scalars().all()]

        result = await session.execute(
            select(SimAccount).where(SimAccount.id == 1)
        )
        acct_row = result.scalar_one_or_none()
        account = _row_to_account(acct_row) if acct_row else None

    logger.info(
        "loaded OMS state: %d orders, %d positions, account=%s",
        len(orders), len(positions), "found" if account else "empty",
    )
    return orders, positions, account


# ---------------------------------------------------------------------------
# Clear (account reset)
# ---------------------------------------------------------------------------

async def clear_all_sim_data() -> None:
    """Delete all rows from sim_orders, sim_positions, sim_account."""
    try:
        async with async_session() as session:
            await session.execute(delete(SimOrder))
            await session.execute(delete(SimPosition))
            await session.execute(delete(SimAccount))
            await session.commit()
        logger.info("cleared all sim data from DB")
    except Exception:
        logger.exception("failed to clear sim data")
