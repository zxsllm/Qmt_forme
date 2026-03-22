"""Pydantic models shared between research and execution layers.

These are *in-memory* data contracts — NOT ORM models.
ORM models live in shared/models/stock.py and map to DB tables.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.shared.interfaces.types import (
    AuditAction,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskAction,
)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

class BarData(BaseModel):
    """Unified bar representation (1min / 5min / daily / realtime)."""
    ts_code: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float = 0.0
    freq: str = "1min"


# ---------------------------------------------------------------------------
# Strategy → OMS
# ---------------------------------------------------------------------------

class Signal(BaseModel):
    """Strategy output — intent to trade, before any risk check."""
    signal_id: UUID = Field(default_factory=uuid4)
    ts_code: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    price: float | None = None          # required for LIMIT orders
    qty: int = 100                       # in shares, must be multiple of 100
    reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderRequest(BaseModel):
    """Post-risk-check order, ready for submission to matcher/broker."""
    order_id: UUID = Field(default_factory=uuid4)
    signal_id: UUID
    ts_code: str
    side: OrderSide
    order_type: OrderType
    price: float | None = None
    qty: int
    created_at: datetime = Field(default_factory=datetime.now)


class Order(BaseModel):
    """Full order record with lifecycle state."""
    order_id: UUID
    signal_id: UUID
    ts_code: str
    side: OrderSide
    order_type: OrderType
    price: float | None = None          # limit price or None for market
    qty: int                            # requested qty
    filled_qty: int = 0
    filled_price: float = 0.0           # average fill price
    status: OrderStatus = OrderStatus.PENDING
    fee: float = 0.0
    slippage: float = 0.0
    reject_reason: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Position & Account
# ---------------------------------------------------------------------------

class Position(BaseModel):
    """Single stock holding."""
    ts_code: str
    qty: int = 0                        # current shares held
    avg_cost: float = 0.0               # average cost per share (incl. fees)
    market_price: float = 0.0           # latest market price
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class Account(BaseModel):
    """Simulated account snapshot."""
    total_asset: float = 1_000_000.0
    cash: float = 1_000_000.0
    frozen: float = 0.0                 # funds locked by pending orders
    market_value: float = 0.0           # sum of position market values
    total_pnl: float = 0.0
    today_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

class RiskCheckResult(BaseModel):
    action: RiskAction
    reason: str = ""
    adjusted_qty: int | None = None     # only when action == REDUCE


# ---------------------------------------------------------------------------
# Fee config (A-share defaults)
# ---------------------------------------------------------------------------

class FeeConfig(BaseModel):
    commission_rate: float = 0.00025    # 万2.5 per side
    min_commission: float = 5.0         # minimum commission per trade
    stamp_tax_rate: float = 0.0005      # 万5 (sell only)
    transfer_fee_rate: float = 0.00001  # 万0.1 (SSE only, both sides)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    action: AuditAction
    order_id: UUID | None = None
    ts_code: str = ""
    detail: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
