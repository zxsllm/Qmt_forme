"""REST API endpoints for the trading engine (OMS / Risk / Account)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.shared.interfaces.types import OrderSide, OrderType, OrderStatus
from app.shared.interfaces.models import Signal
from app.execution.engine import trading_engine
from app.execution.observability.heartbeat import check_heartbeats, send_heartbeat
from app.execution.feed.ws_manager import ws_manager
from app.core.database import async_session

router = APIRouter(prefix="/api/v1", tags=["trading"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SubmitOrderBody(BaseModel):
    ts_code: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    qty: int = 100
    reason: str = ""


class KillSwitchBody(BaseModel):
    reason: str = "manual"


# ---------------------------------------------------------------------------
# Price limit validation
# ---------------------------------------------------------------------------

def _limit_pct(ts_code: str, name: str = "", is_st: bool | None = None) -> float:
    """Return daily price limit percentage based on board type and ST status."""
    code = ts_code.split(".")[0]
    if is_st is None:
        is_st = "ST" in name.upper() if name else False

    if code.startswith("3") or code.startswith("688"):
        return 0.20
    if code.startswith("8"):
        return 0.30
    if is_st:
        return 0.05
    return 0.10


async def _get_price_limits(ts_code: str) -> tuple[float | None, float | None]:
    """Calculate next-day up/down limit from latest close + stock type."""
    async with async_session() as session:
        row = await session.execute(
            text(
                "SELECT d.close, b.name "
                "FROM stock_daily d JOIN stock_basic b ON d.ts_code = b.ts_code "
                "WHERE d.ts_code = :c ORDER BY d.trade_date DESC LIMIT 1"
            ),
            {"c": ts_code},
        )
        result = row.first()
        if result is None:
            return None, None

        close, name = float(result[0]), str(result[1] or "")
        pct = _limit_pct(ts_code, name)
        up_limit = round(close * (1 + pct), 2)
        down_limit = round(close * (1 - pct), 2)
        return up_limit, down_limit


# ---------------------------------------------------------------------------
# Order endpoints
# ---------------------------------------------------------------------------

@router.post("/orders")
async def submit_order(body: SubmitOrderBody):
    # --- A-share: 整手校验 (买入必须100股整数倍, 卖出允许零股清仓) ---
    if body.side == OrderSide.BUY and body.qty % 100 != 0:
        raise HTTPException(status_code=400, detail=f"买入数量 {body.qty} 必须为100股整数倍")
    if body.qty <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于0")

    # --- A-share: 价格tick 0.01 ---
    if body.price is not None and round(body.price * 100) != body.price * 100:
        raise HTTPException(status_code=400, detail=f"价格 {body.price} 必须为0.01的整数倍")

    # --- A-share: 涨跌停限价校验 ---
    if body.order_type == OrderType.LIMIT and body.price is not None:
        up_limit, down_limit = await _get_price_limits(body.ts_code)
        if up_limit and body.price > up_limit:
            raise HTTPException(
                status_code=400,
                detail=f"价格 {body.price} 超过涨停价 {up_limit}，订单被拒绝",
            )
        if down_limit and body.price < down_limit:
            raise HTTPException(
                status_code=400,
                detail=f"价格 {body.price} 低于跌停价 {down_limit}，订单被拒绝",
            )

    signal = Signal(
        ts_code=body.ts_code,
        side=body.side,
        order_type=body.order_type,
        price=body.price,
        qty=body.qty,
        reason=body.reason,
    )
    result = trading_engine.submit_signal(signal)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)

    from app.execution.feed.scheduler import scheduler
    scheduler.add_watch_code(body.ts_code)

    return result.model_dump(mode="json")


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: UUID):
    result = trading_engine.cancel_order(order_id)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    return result.model_dump(mode="json")


@router.get("/orders")
async def list_orders(status: OrderStatus | None = None):
    orders = trading_engine.get_orders(status=status)
    return {"count": len(orders), "data": [o.model_dump(mode="json") for o in orders]}


# ---------------------------------------------------------------------------
# Position / Account
# ---------------------------------------------------------------------------

@router.get("/positions")
async def list_positions():
    positions = trading_engine.get_positions()
    return {"count": len(positions), "data": [p.model_dump(mode="json") for p in positions]}


@router.get("/account")
async def get_account():
    return trading_engine.get_account().model_dump(mode="json")


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

@router.get("/risk/status")
async def risk_status():
    return trading_engine.get_risk_status()


@router.post("/risk/kill-switch")
async def activate_kill(body: KillSwitchBody):
    return trading_engine.activate_kill_switch(body.reason)


@router.delete("/risk/kill-switch")
async def deactivate_kill():
    return trading_engine.deactivate_kill_switch()


# ---------------------------------------------------------------------------
# Account reset (simulation only)
# ---------------------------------------------------------------------------

@router.post("/account/reset")
async def reset_account():
    """Reset the simulated account to initial state (clear positions/orders)."""
    from app.execution.oms.order_manager import OrderManager
    from app.execution.oms.position_book import PositionBook
    from app.execution.oms.account import AccountManager
    from app.execution.persistence import clear_all_sim_data, save_batch

    trading_engine.order_mgr = OrderManager()
    trading_engine.position_book = PositionBook()
    trading_engine.account_mgr = AccountManager(1_000_000.0)
    trading_engine.pre_trade.reset_daily()
    trading_engine.realtime_risk.reset()
    trading_engine.kill_switch.deactivate()
    trading_engine._audit_buffer.clear()

    await clear_all_sim_data()
    await save_batch(account=trading_engine.account_mgr.account)

    return {"status": "ok", "message": "account reset to initial state"}


# ---------------------------------------------------------------------------
# Strategy runner
# ---------------------------------------------------------------------------

class StrategyStartBody(BaseModel):
    strategy_name: str = "ma_crossover"
    params: dict = {}
    codes: list[str] = ["000001.SZ"]


@router.post("/strategy/start")
async def start_strategy(body: StrategyStartBody):
    from app.execution.strategy_runner import strategy_runner
    from app.research.strategies.ma_crossover import MACrossover

    registry: dict[str, type] = {
        "ma_crossover": MACrossover,
    }
    cls = registry.get(body.strategy_name)
    if cls is None:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {body.strategy_name}")

    strategy = cls(params=body.params or None)
    result = strategy_runner.start_strategy(strategy, body.codes)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/strategy/{name}/stop")
async def stop_strategy(name: str):
    from app.execution.strategy_runner import strategy_runner
    result = strategy_runner.stop_strategy(name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/strategy/running")
async def list_running_strategies():
    from app.execution.strategy_runner import strategy_runner
    return strategy_runner.status()


# ---------------------------------------------------------------------------
# Market data scheduler
# ---------------------------------------------------------------------------

@router.get("/feed/status")
async def feed_status():
    from app.execution.feed.scheduler import scheduler
    return scheduler.status()


class FeedStartBody(BaseModel):
    codes: list[str] = ["000001.SZ"]


@router.post("/feed/start")
async def feed_start(body: FeedStartBody):
    from app.execution.feed.scheduler import scheduler
    await scheduler.start(body.codes)
    return scheduler.status()


@router.post("/feed/stop")
async def feed_stop():
    from app.execution.feed.scheduler import scheduler
    await scheduler.stop()
    return scheduler.status()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

@router.get("/observability/heartbeats")
async def get_heartbeats():
    return check_heartbeats()


@router.get("/observability/ws-clients")
async def get_ws_clients():
    return {"count": ws_manager.connection_count}


@router.get("/observability/audit")
async def get_audit_buffer():
    events = trading_engine.flush_audit()
    return {"count": len(events), "data": [e.model_dump(mode="json") for e in events]}
