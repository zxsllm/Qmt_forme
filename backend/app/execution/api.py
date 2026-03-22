"""REST API endpoints for the trading engine (OMS / Risk / Account)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.shared.interfaces.types import OrderSide, OrderType, OrderStatus
from app.shared.interfaces.models import Signal
from app.execution.engine import trading_engine
from app.execution.observability.heartbeat import check_heartbeats, send_heartbeat
from app.execution.feed.ws_manager import ws_manager

router = APIRouter(prefix="/api/v1", tags=["trading"])


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
# Order endpoints
# ---------------------------------------------------------------------------

@router.post("/orders")
async def submit_order(body: SubmitOrderBody):
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
