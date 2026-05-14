"""Persistence layer — bridges in-memory OMS state to sim_* DB tables.

Per-strategy isolation: every save/load takes a `strategy_name` argument so
Pattern1 / Pattern2 / manual orders each maintain a separate book.

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

def _order_to_row(o: Order, strategy_name: str, *, signal_extras: dict | None = None) -> dict:
    """Convert Order → DB row. Order 自带 sell_anchor / pick_role / lot_id 等，
    优先从 o 取；signal_extras 仅作 fallback（兼容老调用方式）。"""
    extras = signal_extras or {}
    return {
        "order_id": str(o.order_id),
        "strategy_name": strategy_name,
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
        "sell_anchor": o.sell_anchor or extras.get("sell_anchor", ""),
        "sell_anchor_time": o.sell_anchor_time or extras.get("sell_anchor_time"),
        "sell_reason": o.sell_reason or extras.get("sell_reason", ""),
        "pick_kind": o.pick_kind or extras.get("pick_kind", "stock"),
        "pick_role": o.pick_role or extras.get("pick_role", ""),
        "buy_anchor": o.buy_anchor or extras.get("buy_anchor", "market"),
        "buy_anchor_time": o.buy_anchor_time or extras.get("buy_anchor_time"),
        "underlying_code": o.underlying_code or extras.get("underlying_code"),
        "lot_id": o.lot_id or extras.get("lot_id", ""),
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
        lot_id=row.lot_id or "",
        sell_anchor=row.sell_anchor or "",
        sell_anchor_time=row.sell_anchor_time,
        sell_reason=row.sell_reason or "",
        pick_kind=row.pick_kind or "stock",
        pick_role=row.pick_role or "",
        buy_anchor=row.buy_anchor or "market",
        buy_anchor_time=row.buy_anchor_time,
        underlying_code=row.underlying_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _position_to_row(p: Position, strategy_name: str) -> dict:
    return {
        "lot_id": p.lot_id or p.ts_code,  # legacy fallback
        "strategy_name": strategy_name,
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


def _account_to_row(a: Account, strategy_name: str) -> dict:
    return {
        "strategy_name": strategy_name,
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
    strategy_name: str,
    *,
    orders: list[Order] | None = None,
    positions: list[Position] | None = None,
    account: Account | None = None,
    order_extras: dict[str, dict] | None = None,
) -> None:
    """Persist orders/positions/account in one transaction (non-blocking).

    strategy_name: 必填。每个策略一份账本（PK = strategy_name on sim_account；
    sim_orders/sim_positions/sim_trades 加 strategy_name 列做隔离）。

    order_extras: optional {order_id_str → {sell_anchor, pick_kind, ...}} to attach
    pattern-aware fields to SimOrder rows (legacy fallback).
    """
    try:
        async with async_session() as session:
            if orders:
                for o in orders:
                    extras = (order_extras or {}).get(str(o.order_id))
                    row = _order_to_row(o, strategy_name, signal_extras=extras)
                    stmt = pg_insert(SimOrder).values(**row).on_conflict_do_update(
                        index_elements=["order_id"],
                        set_={k: v for k, v in row.items() if k != "order_id"},
                    )
                    await session.execute(stmt)
            if positions:
                for p in positions:
                    row = _position_to_row(p, strategy_name)
                    stmt = pg_insert(SimPosition).values(**row).on_conflict_do_update(
                        index_elements=["lot_id"],
                        set_={k: v for k, v in row.items() if k != "lot_id"},
                    )
                    await session.execute(stmt)
            if account:
                row = _account_to_row(account, strategy_name)
                stmt = pg_insert(SimAccount).values(**row).on_conflict_do_update(
                    index_elements=["strategy_name"],
                    set_={k: v for k, v in row.items() if k != "strategy_name"},
                )
                await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.exception("failed to persist OMS batch (strategy=%s)", strategy_name)


# ---------------------------------------------------------------------------
# Load (startup recovery)
# ---------------------------------------------------------------------------

async def load_all_state(strategy_name: str) -> tuple[list[Order], list[Position], Account | None]:
    """Read persisted OMS state for one strategy."""
    async with async_session() as session:
        result = await session.execute(
            select(SimOrder).where(SimOrder.strategy_name == strategy_name)
        )
        orders = [_row_to_order(r) for r in result.scalars().all()]

        result = await session.execute(
            select(SimPosition).where(SimPosition.strategy_name == strategy_name)
        )
        positions = [_row_to_position(r) for r in result.scalars().all()]

        result = await session.execute(
            select(SimAccount).where(SimAccount.strategy_name == strategy_name)
        )
        acct_row = result.scalar_one_or_none()
        account = _row_to_account(acct_row) if acct_row else None

    logger.info(
        "loaded OMS state for '%s': %d orders, %d positions, account=%s",
        strategy_name, len(orders), len(positions), "found" if account else "empty",
    )
    return orders, positions, account


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

async def clear_all_sim_data(strategy_name: str | None = None) -> None:
    """Delete rows from sim_orders/sim_positions/sim_account.

    strategy_name=None → 全清（reset 所有策略账本）；指定时只清那一个。
    """
    try:
        async with async_session() as session:
            if strategy_name is None:
                await session.execute(delete(SimOrder))
                await session.execute(delete(SimPosition))
                await session.execute(delete(SimAccount))
                logger.info("cleared ALL sim data from DB")
            else:
                await session.execute(
                    delete(SimOrder).where(SimOrder.strategy_name == strategy_name)
                )
                await session.execute(
                    delete(SimPosition).where(SimPosition.strategy_name == strategy_name)
                )
                await session.execute(
                    delete(SimAccount).where(SimAccount.strategy_name == strategy_name)
                )
                logger.info("cleared sim data for strategy='%s'", strategy_name)
            await session.commit()
    except Exception:
        logger.exception("failed to clear sim data (strategy=%s)", strategy_name)
