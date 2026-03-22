from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base


class StockBasic(Base):
    __tablename__ = "stock_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(String(32))
    area: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(32))
    market: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[str | None] = mapped_column(String(8))
    list_status: Mapped[str | None] = mapped_column(String(1))
    exchange: Mapped[str | None] = mapped_column(String(8))
    curr_type: Mapped[str | None] = mapped_column(String(8))
    is_hs: Mapped[str | None] = mapped_column(String(1))


class TradeCal(Base):
    __tablename__ = "trade_cal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str | None] = mapped_column(String(8))
    cal_date: Mapped[str] = mapped_column(String(8), index=True)
    is_open: Mapped[int | None] = mapped_column(Integer)
    pretrade_date: Mapped[str | None] = mapped_column(String(8))


class StockDaily(Base):
    __tablename__ = "stock_daily"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)


class DailyBasic(Base):
    __tablename__ = "daily_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    close: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    turnover_rate_f: Mapped[float | None] = mapped_column(Float)
    volume_ratio: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    pe_ttm: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ps: Mapped[float | None] = mapped_column(Float)
    ps_ttm: Mapped[float | None] = mapped_column(Float)
    dv_ratio: Mapped[float | None] = mapped_column(Float)
    dv_ttm: Mapped[float | None] = mapped_column(Float)
    total_share: Mapped[float | None] = mapped_column(Float)
    float_share: Mapped[float | None] = mapped_column(Float)
    free_share: Mapped[float | None] = mapped_column(Float)
    total_mv: Mapped[float | None] = mapped_column(Float)
    circ_mv: Mapped[float | None] = mapped_column(Float)


class IndexBasic(Base):
    __tablename__ = "index_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    fullname: Mapped[str | None] = mapped_column(String(128))
    market: Mapped[str | None] = mapped_column(String(16))
    publisher: Mapped[str | None] = mapped_column(String(32))
    index_type: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32))
    base_date: Mapped[str | None] = mapped_column(String(8))
    base_point: Mapped[float | None] = mapped_column(Float)
    list_date: Mapped[str | None] = mapped_column(String(8))


class IndexDaily(Base):
    __tablename__ = "index_daily"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)


class IndexClassify(Base):
    __tablename__ = "index_classify"

    index_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    industry_name: Mapped[str | None] = mapped_column(String(32))
    parent_code: Mapped[str | None] = mapped_column(String(16))
    level: Mapped[str | None] = mapped_column(String(4))
    industry_code: Mapped[str | None] = mapped_column(String(16))
    is_pub: Mapped[str | None] = mapped_column(String(1))
    src: Mapped[str | None] = mapped_column(String(16))


class StockMinKline(Base):
    """Mapped to the partitioned stock_min_kline table (created via raw SQL)."""

    __tablename__ = "stock_min_kline"
    __table_args__ = {"extend_existing": True}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    freq: Mapped[str] = mapped_column(String(8), primary_key=True, default="1min")
    open: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)


# =========================================================================
# Phase 3: Simulated trading tables
# =========================================================================

class SimOrder(Base):
    __tablename__ = "sim_orders"

    order_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    signal_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))            # BUY / SELL
    order_type: Mapped[str] = mapped_column(String(8))      # MARKET / LIMIT
    price: Mapped[float | None] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()"), onupdate=datetime.now
    )


class SimTrade(Base):
    """Individual fill / execution record."""
    __tablename__ = "sim_trades"

    trade_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    order_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    traded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


class SimPosition(Base):
    """Per-stock position snapshot, one row per ts_code."""
    __tablename__ = "sim_positions"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    market_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()"), onupdate=datetime.now
    )


class SimAccount(Base):
    """Single-row account snapshot.  id=1 always."""
    __tablename__ = "sim_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    total_asset: Mapped[float] = mapped_column(Float, default=1_000_000.0)
    cash: Mapped[float] = mapped_column(Float, default=1_000_000.0)
    frozen: Mapped[float] = mapped_column(Float, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    today_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()"), onupdate=datetime.now
    )


class AuditLog(Base):
    """Immutable audit trail for all trading actions."""
    __tablename__ = "audit_log"

    event_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    order_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False))
    ts_code: Mapped[str] = mapped_column(String(16), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()"), index=True
    )
