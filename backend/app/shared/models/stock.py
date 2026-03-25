from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, text
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
# Phase 4: Backtest support tables
# =========================================================================

class StockLimit(Base):
    """Daily up/down limit prices for all stocks."""
    __tablename__ = "stock_limit"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    up_limit: Mapped[float | None] = mapped_column(Float)
    down_limit: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)


class SuspendD(Base):
    """Daily suspension records (S=suspend, R=resume)."""
    __tablename__ = "suspend_d"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    suspend_type: Mapped[str | None] = mapped_column(String(4))
    suspend_timing: Mapped[str | None] = mapped_column(String(32))


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
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
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


# =========================================================================
# Phase 4: Strategy & Backtest metadata tables
# =========================================================================

class StrategyMeta(Base):
    """Registry of all strategies available for backtesting / trading."""
    __tablename__ = "strategy_meta"

    strategy_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    default_params: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    promotion_level: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


class BacktestRun(Base):
    """One backtest execution record with config + summary stats."""
    __tablename__ = "backtest_run"

    run_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    equity_json: Mapped[str] = mapped_column(Text, default="[]")
    trades_json: Mapped[str] = mapped_column(Text, default="[]")
    filtered_json: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")


class PromotionHistory(Base):
    """Track strategy promotions / demotions through the pipeline."""
    __tablename__ = "promotion_history"

    record_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    from_level: Mapped[int] = mapped_column(Integer)
    to_level: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    backtest_run_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


# =========================================================================
# P2-Plus: 资讯仪表盘新增表
# =========================================================================

class MoneyFlowDC(Base):
    """Per-stock daily money flow from Tushare moneyflow_dc."""
    __tablename__ = "moneyflow_dc"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    buy_sm_amount: Mapped[float | None] = mapped_column(Float)
    sell_sm_amount: Mapped[float | None] = mapped_column(Float)
    buy_md_amount: Mapped[float | None] = mapped_column(Float)
    sell_md_amount: Mapped[float | None] = mapped_column(Float)
    buy_lg_amount: Mapped[float | None] = mapped_column(Float)
    sell_lg_amount: Mapped[float | None] = mapped_column(Float)
    buy_elg_amount: Mapped[float | None] = mapped_column(Float)
    sell_elg_amount: Mapped[float | None] = mapped_column(Float)
    net_mf_amount: Mapped[float | None] = mapped_column(Float)


class StockNews(Base):
    """Market news from Tushare news API."""
    __tablename__ = "stock_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    channels: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str | None] = mapped_column(String(64))


class StockAnns(Base):
    """Company announcements from Tushare anns API."""
    __tablename__ = "stock_anns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(Text)


class StockST(Base):
    """Daily ST stock list from Tushare stock_st API."""
    __tablename__ = "stock_st"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    type: Mapped[str | None] = mapped_column(String(8))
    type_name: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_stock_st_code_date"),
    )


class AdjFactor(Base):
    """Daily adjustment factor from Tushare adj_factor API."""
    __tablename__ = "adj_factor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    adj_factor: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_adj_factor_code_date"),
    )


class SwDaily(Base):
    """Shenwan industry index daily bars from Tushare sw_daily API."""
    __tablename__ = "sw_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    open: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    float_mv: Mapped[float | None] = mapped_column(Float)
    total_mv: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_sw_daily_code_date"),
    )


class StkAuction(Base):
    """Opening auction data from Tushare stk_auction API."""
    __tablename__ = "stk_auction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    vol: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    volume_ratio: Mapped[float | None] = mapped_column(Float)
    float_share: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_stk_auction_code_date"),
    )


class EcoCal(Base):
    """Global economic calendar from Tushare eco_cal API."""
    __tablename__ = "eco_cal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str | None] = mapped_column(String(8), index=True)
    time: Mapped[str | None] = mapped_column(String(8))
    currency: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(64))
    event: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(String(64))
    pre_value: Mapped[str | None] = mapped_column(String(64))
    fore_value: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("date", "time", "event", name="uq_eco_cal_date_time_event"),
    )


class MoneyflowIndThs(Base):
    """THS industry money flow from Tushare moneyflow_ind_ths API."""
    __tablename__ = "moneyflow_ind_ths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    industry: Mapped[str | None] = mapped_column(String(32))
    lead_stock: Mapped[str | None] = mapped_column(String(16))
    close: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)
    company_num: Mapped[int | None] = mapped_column(Integer)
    pct_change_stock: Mapped[float | None] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float)
    net_buy_amount: Mapped[float | None] = mapped_column(Float)
    net_sell_amount: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_mf_ind_ths_code_date"),
    )


class IndexGlobal(Base):
    """International index daily bars from Tushare index_global API."""
    __tablename__ = "index_global"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    open: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_index_global_code_date"),
    )


class ConceptList(Base):
    """Concept/theme sector list from Tushare concept API."""
    __tablename__ = "concept_list"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    src: Mapped[str | None] = mapped_column(String(16))


class ConceptDetail(Base):
    """Concept-to-stock mapping from Tushare concept_detail API."""
    __tablename__ = "concept_detail"

    concept_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    concept_name: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(32))
