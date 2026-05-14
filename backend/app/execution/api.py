"""REST API endpoints for the trading engine (OMS / Risk / Account)."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.shared.interfaces.types import OrderSide, OrderType, OrderStatus
from app.shared.interfaces.models import Position, Signal
from app.execution.engine import trading_engine
from app.execution.observability.heartbeat import check_heartbeats, send_heartbeat
from app.execution.feed.scheduler import get_rt_snapshot
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


async def _latest_position_prices(codes: list[str]) -> dict[str, float]:
    """Resolve latest prices for held codes from today's snapshot or latest daily close."""
    if not codes:
        return {}

    prices: dict[str, float] = {}
    snapshot, snapshot_ts = get_rt_snapshot()
    snap_is_today = bool(snapshot and snapshot_ts and date.fromtimestamp(snapshot_ts) == date.today())
    missing_codes: list[str] = []

    if snap_is_today:
        for code in codes:
            row = snapshot.get(code)
            close = float(row.get("close", 0)) if row else 0.0
            if close > 0:
                prices[code] = close
            else:
                missing_codes.append(code)
    else:
        missing_codes = codes

    if not missing_codes:
        return prices

    placeholders = ", ".join(f":c{i}" for i in range(len(missing_codes)))
    params = {f"c{i}": code for i, code in enumerate(missing_codes)}
    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT DISTINCT ON (ts_code) ts_code, close
                FROM stock_daily
                WHERE ts_code IN ({placeholders})
                ORDER BY ts_code, trade_date DESC
            """),
            params,
        )
        for ts_code, close in result.all():
            if close is not None and float(close) > 0:
                prices[ts_code] = float(close)

    return prices


def _resolve_engine(strategy: str):
    """根据 strategy 名拿对应 engine。'default' → 全局 manual engine；
    其他 → strategy_runner 持有的策略 engine。"""
    from app.execution.strategy_runner import strategy_runner
    eng = strategy_runner.get_engine(strategy)
    if eng is None:
        raise HTTPException(
            status_code=404,
            detail=f"strategy '{strategy}' not running (start it first via /strategy/start)",
        )
    return eng


async def _refresh_positions_from_market(eng) -> list[Position]:
    """Refresh in-memory position marks，返回 lot 级别（多 lot 架构下每 lot 一行）。"""
    positions = eng.get_positions()
    if not positions:
        eng.account_mgr.refresh(eng.position_book)
        return eng.position_book.get_all_lots()

    prices = await _latest_position_prices([p.ts_code for p in positions if p.qty > 0])
    for pos in positions:
        price = prices.get(pos.ts_code)
        if price is not None and price > 0:
            eng.position_book.update_market_price(pos.ts_code, price)

    eng.account_mgr.refresh(eng.position_book)
    # lot 级别返回（含 lot_id / sell_anchor / pick_role 等 OMS 字段）
    return [lot for lot in eng.position_book.get_all_lots() if lot.qty > 0]


# ---------------------------------------------------------------------------
# Order endpoints
# ---------------------------------------------------------------------------

@router.post("/orders")
async def submit_order(body: SubmitOrderBody, strategy: str = "default"):
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

    eng = _resolve_engine(strategy)
    signal = Signal(
        ts_code=body.ts_code,
        side=body.side,
        order_type=body.order_type,
        price=body.price,
        qty=body.qty,
        reason=body.reason,
    )
    result = eng.submit_signal(signal)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)

    from app.execution.feed.scheduler import scheduler
    scheduler.add_watch_code(body.ts_code)

    return result.model_dump(mode="json")


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: UUID, strategy: str = "default"):
    eng = _resolve_engine(strategy)
    result = eng.cancel_order(order_id)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    return result.model_dump(mode="json")


@router.get("/orders")
async def list_orders(status: OrderStatus | None = None, strategy: str = "default"):
    eng = _resolve_engine(strategy)
    orders = eng.get_orders(status=status)
    return {"count": len(orders), "data": [o.model_dump(mode="json") for o in orders]}


# ---------------------------------------------------------------------------
# Position / Account
# ---------------------------------------------------------------------------

@router.get("/positions")
async def list_positions(strategy: str = "default"):
    eng = _resolve_engine(strategy)
    positions = await _refresh_positions_from_market(eng)
    return {"count": len(positions), "data": [p.model_dump(mode="json") for p in positions]}


@router.get("/account")
async def get_account(strategy: str = "default"):
    eng = _resolve_engine(strategy)
    await _refresh_positions_from_market(eng)
    return eng.get_account().model_dump(mode="json")


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

@router.get("/risk/status")
async def risk_status(strategy: str = "default"):
    eng = _resolve_engine(strategy)
    return eng.get_risk_status()


@router.post("/risk/kill-switch")
async def activate_kill(body: KillSwitchBody, strategy: str = "default"):
    eng = _resolve_engine(strategy)
    return eng.activate_kill_switch(body.reason)


@router.delete("/risk/kill-switch")
async def deactivate_kill(strategy: str = "default"):
    eng = _resolve_engine(strategy)
    return eng.deactivate_kill_switch()


# ---------------------------------------------------------------------------
# Account reset (simulation only)
# ---------------------------------------------------------------------------

@router.post("/account/reset")
async def reset_account(strategy: str = "default"):
    """Reset 1 个策略账户到初始状态 + 清空该策略的 sim_orders / sim_positions。

    strategy='default' → 清空 manual 账户（不影响 pattern_01/02 的账本）。
    """
    from app.execution.oms.order_manager import OrderManager
    from app.execution.oms.position_book import PositionBook
    from app.execution.oms.account import AccountManager
    from app.execution.persistence import clear_all_sim_data, save_batch

    eng = _resolve_engine(strategy)
    eng.order_mgr = OrderManager()
    eng.position_book = PositionBook()
    eng.account_mgr = AccountManager(1_000_000.0)
    eng.pre_trade.reset_daily()
    eng.realtime_risk.reset()
    eng.kill_switch.deactivate()
    eng._audit_buffer.clear()

    await clear_all_sim_data(strategy_name=strategy)
    await save_batch(strategy, account=eng.account_mgr.account)

    return {"status": "ok", "strategy": strategy, "message": "account reset to initial state"}


# ---------------------------------------------------------------------------
# Strategy runner
# ---------------------------------------------------------------------------

class StrategyStartBody(BaseModel):
    strategy_name: str = "ma_crossover"
    params: dict = {}
    codes: list[str] = ["000001.SZ"]
    initial_capital: float = 1_000_000.0  # 每策略独立资金池（方案 A）


@router.post("/strategy/start")
async def start_strategy(body: StrategyStartBody):
    from app.execution.strategy_runner import strategy_runner
    from app.execution.feed.scheduler import scheduler
    from app.research.strategies.ma_crossover import MACrossover
    from app.research.strategies.pattern_01_long1_natural import Pattern01
    from app.research.strategies.pattern_02_long1_yizi import Pattern02
    from app.research.strategies.base_long_head_strategy import BaseLongHeadStrategy

    # F15: execution/api.py 作为策略 registry 边界，允许 import research.strategies
    registry: dict[str, type] = {
        "ma_crossover": MACrossover,
        "pattern_01": Pattern01,
        "pattern_02": Pattern02,
    }
    cls = registry.get(body.strategy_name)
    if cls is None:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {body.strategy_name}")

    try:
        strategy = cls(params=body.params or None)
    except TypeError:
        strategy = cls()
        if body.params:
            strategy.params = body.params

    # Pattern1/2 必须先 warm_up（async 预拉静态数据），universe 由 warm_up 计算
    codes = body.codes
    if isinstance(strategy, BaseLongHeadStrategy):
        today_str = date.today().strftime("%Y%m%d")
        async with async_session() as session:
            await strategy.warm_up(session, today_str)
        universe = strategy.get_universe()
        if not universe:
            raise HTTPException(
                status_code=500,
                detail=f"{body.strategy_name} warm_up 失败 — sectors 为空，检查盘前数据",
            )
        codes = universe
        # 把 Pattern universe 并入 scheduler 监控
        for c in universe:
            scheduler.add_watch_code(c)
        logger.info(
            "%s warm_up done, universe=%d codes (stocks+CBs), scheduler watch updated",
            strategy.name, len(universe),
        )

    result = await strategy_runner.start_strategy(
        strategy, codes, initial_capital=body.initial_capital,
    )
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
