from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
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


class StockNamechange(Base):
    """Stock name change history from Tushare namechange API."""
    __tablename__ = "stock_namechange"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    start_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str | None] = mapped_column(String(8))
    ann_date: Mapped[str | None] = mapped_column(String(8), index=True)
    change_reason: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("ts_code", "start_date", name="uq_namechange_code_start"),
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


# ---------------------------------------------------------------------------
# Phase 4.8: 四维能力建设 — 基本面
# ---------------------------------------------------------------------------

class FinaIndicator(Base):
    """Key financial indicators from Tushare fina_indicator API."""
    __tablename__ = "fina_indicator"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str] = mapped_column(String(8), index=True)
    eps: Mapped[float | None] = mapped_column(Float)
    dt_eps: Mapped[float | None] = mapped_column(Float)
    profit_dedt: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    roe_waa: Mapped[float | None] = mapped_column(Float)
    roe_dt: Mapped[float | None] = mapped_column(Float)
    roa: Mapped[float | None] = mapped_column(Float)
    netprofit_margin: Mapped[float | None] = mapped_column(Float)
    grossprofit_margin: Mapped[float | None] = mapped_column(Float)
    debt_to_assets: Mapped[float | None] = mapped_column(Float)
    ocfps: Mapped[float | None] = mapped_column(Float)
    bps: Mapped[float | None] = mapped_column(Float)
    current_ratio: Mapped[float | None] = mapped_column(Float)
    quick_ratio: Mapped[float | None] = mapped_column(Float)
    netprofit_yoy: Mapped[float | None] = mapped_column(Float)
    dt_netprofit_yoy: Mapped[float | None] = mapped_column(Float)
    tr_yoy: Mapped[float | None] = mapped_column(Float)
    or_yoy: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", name="uq_fina_indicator_code_end"),
    )


class Income(Base):
    """Income statement from Tushare income API."""
    __tablename__ = "income"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    f_ann_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str] = mapped_column(String(8), index=True)
    report_type: Mapped[str | None] = mapped_column(String(4))
    total_revenue: Mapped[float | None] = mapped_column(Float)
    revenue: Mapped[float | None] = mapped_column(Float)
    oper_cost: Mapped[float | None] = mapped_column(Float)
    sell_exp: Mapped[float | None] = mapped_column(Float)
    admin_exp: Mapped[float | None] = mapped_column(Float)
    fin_exp: Mapped[float | None] = mapped_column(Float)
    rd_exp: Mapped[float | None] = mapped_column(Float)
    operate_profit: Mapped[float | None] = mapped_column(Float)
    total_profit: Mapped[float | None] = mapped_column(Float)
    income_tax: Mapped[float | None] = mapped_column(Float)
    n_income: Mapped[float | None] = mapped_column(Float)
    n_income_attr_p: Mapped[float | None] = mapped_column(Float)
    basic_eps: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "report_type", name="uq_income_code_end_rpt"),
    )


class Forecast(Base):
    """Earnings forecast from Tushare forecast API."""
    __tablename__ = "forecast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8), index=True)
    end_date: Mapped[str] = mapped_column(String(8))
    type: Mapped[str | None] = mapped_column(String(16))
    p_change_min: Mapped[float | None] = mapped_column(Float)
    p_change_max: Mapped[float | None] = mapped_column(Float)
    net_profit_min: Mapped[float | None] = mapped_column(Float)
    net_profit_max: Mapped[float | None] = mapped_column(Float)
    last_parent_net: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(16), server_default="tushare")

    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "end_date", name="uq_forecast_code_ann_end"),
    )


class FinaMainbz(Base):
    """Main business composition from Tushare fina_mainbz API."""
    __tablename__ = "fina_mainbz"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    end_date: Mapped[str] = mapped_column(String(8), index=True)
    bz_item: Mapped[str | None] = mapped_column(String(128))
    bz_sales: Mapped[float | None] = mapped_column(Float)
    bz_profit: Mapped[float | None] = mapped_column(Float)
    bz_cost: Mapped[float | None] = mapped_column(Float)
    curr_type: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "bz_item", name="uq_fina_mainbz_code_end_item"),
    )


class DisclosureDate(Base):
    """Financial report disclosure schedule from Tushare disclosure_date API."""
    __tablename__ = "disclosure_date"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str] = mapped_column(String(8), index=True)
    pre_date: Mapped[str | None] = mapped_column(String(8))
    actual_date: Mapped[str | None] = mapped_column(String(8))
    modify_date: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", name="uq_disclosure_date_code_end"),
    )


# ---------------------------------------------------------------------------
# Phase 4.8: 四维能力建设 — 情绪面
# ---------------------------------------------------------------------------

class LimitListThs(Base):
    """THS limit-up/down board list from Tushare limit_list_ths API."""
    __tablename__ = "limit_list_ths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    pct_chg: Mapped[float | None] = mapped_column(Float)
    limit_type: Mapped[str | None] = mapped_column(String(16))
    first_lu_time: Mapped[str | None] = mapped_column(String(32))
    last_lu_time: Mapped[str | None] = mapped_column(String(32))
    open_num: Mapped[int | None] = mapped_column(Integer)
    limit_amount: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    tag: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "limit_type", name="uq_limit_list_ths_dtcl"),
    )


class LimitStats(Base):
    """Daily limit-up/down/bomb statistics from Tushare limit_list_d API."""
    __tablename__ = "limit_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    industry: Mapped[str | None] = mapped_column(String(32))
    close: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    limit_amount: Mapped[float | None] = mapped_column(Float)
    float_mv: Mapped[float | None] = mapped_column(Float)
    first_time: Mapped[str | None] = mapped_column(String(16))
    last_time: Mapped[str | None] = mapped_column(String(16))
    open_times: Mapped[int | None] = mapped_column(Integer)
    limit_times: Mapped[int | None] = mapped_column(Integer)
    limit: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "limit", name="uq_limit_stats_dtcl"),
    )


class LimitStep(Base):
    """Consecutive limit-up ladder from Tushare limit_step API."""
    __tablename__ = "limit_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    nums: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_limit_step_dtc"),
    )


class TopList(Base):
    """Dragon-tiger board daily details from Tushare top_list API."""
    __tablename__ = "top_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    close: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    l_sell: Mapped[float | None] = mapped_column(Float)
    l_buy: Mapped[float | None] = mapped_column(Float)
    l_amount: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)
    net_rate: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_top_list_dtc"),
    )


class HmDetail(Base):
    """Hot money (游资) daily trading details from Tushare hm_detail API."""
    __tablename__ = "hm_detail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ts_name: Mapped[str | None] = mapped_column(String(32))
    buy_amount: Mapped[float | None] = mapped_column(Float)
    sell_amount: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)
    hm_name: Mapped[str | None] = mapped_column(String(64))
    tag: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "hm_name", name="uq_hm_detail_dtcn"),
    )


class LimitCptList(Base):
    """Strongest limit-up sector statistics from Tushare limit_cpt_list API."""
    __tablename__ = "limit_cpt_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(64))
    days: Mapped[int | None] = mapped_column(Integer)
    up_stat: Mapped[str | None] = mapped_column(String(32))
    cons_nums: Mapped[int | None] = mapped_column(Integer)
    up_nums: Mapped[int | None] = mapped_column(Integer)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_limit_cpt_list_dtc"),
    )


class DcHot(Base):
    """Eastmoney App hot stock list from Tushare dc_hot API."""
    __tablename__ = "dc_hot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    data_type: Mapped[str | None] = mapped_column(String(32))
    ts_code: Mapped[str | None] = mapped_column(String(16), index=True)
    ts_name: Mapped[str | None] = mapped_column(String(32))
    rank: Mapped[int | None] = mapped_column(Integer)
    pct_change: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "data_type", name="uq_dc_hot_dtcdt"),
    )


# ---------------------------------------------------------------------------
# Phase 4.8: 四维能力建设 — 消息面分类
# ---------------------------------------------------------------------------

class NewsClassified(Base):
    """Classification result for stock_news entries."""
    __tablename__ = "news_classified"

    news_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_scope: Mapped[str] = mapped_column(String(16), index=True)
    time_slot: Mapped[str] = mapped_column(String(16), index=True)
    sentiment: Mapped[str] = mapped_column(String(16), index=True, default="neutral")
    related_codes: Mapped[list | None] = mapped_column(JSONB)
    related_industries: Mapped[list | None] = mapped_column(JSONB)
    keywords: Mapped[list | None] = mapped_column(JSONB)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


class AnnsClassified(Base):
    """Classification result for stock_anns entries."""
    __tablename__ = "anns_classified"

    anns_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ann_type: Mapped[str] = mapped_column(String(32), index=True)
    sentiment: Mapped[str] = mapped_column(String(16), index=True, default="neutral")
    keywords: Mapped[str | None] = mapped_column(Text)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


# ---------------------------------------------------------------------------
# Convertible Bond (可转债)
# ---------------------------------------------------------------------------

class CbBasic(Base):
    """Convertible bond basic info from Tushare cb_basic API."""
    __tablename__ = "cb_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    bond_short_name: Mapped[str | None] = mapped_column(String(32))
    stk_code: Mapped[str | None] = mapped_column(String(16), index=True)
    stk_short_name: Mapped[str | None] = mapped_column(String(32))
    maturity: Mapped[float | None] = mapped_column(Float)
    maturity_date: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[str | None] = mapped_column(String(8))
    delist_date: Mapped[str | None] = mapped_column(String(8))
    exchange: Mapped[str | None] = mapped_column(String(8))
    conv_start_date: Mapped[str | None] = mapped_column(String(8))
    conv_end_date: Mapped[str | None] = mapped_column(String(8))
    conv_price: Mapped[float | None] = mapped_column(Float)
    first_conv_price: Mapped[float | None] = mapped_column(Float)
    issue_size: Mapped[float | None] = mapped_column(Float)
    remain_size: Mapped[float | None] = mapped_column(Float)
    call_clause: Mapped[str | None] = mapped_column(Text)
    put_clause: Mapped[str | None] = mapped_column(Text)
    reset_clause: Mapped[str | None] = mapped_column(Text)
    conv_clause: Mapped[str | None] = mapped_column(Text)
    par: Mapped[float | None] = mapped_column(Float)
    issue_price: Mapped[float | None] = mapped_column(Float)


class CbDaily(Base):
    """Convertible bond daily quotes from Tushare cb_daily API."""
    __tablename__ = "cb_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    pre_close: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    vol: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    bond_value: Mapped[float | None] = mapped_column(Float)
    bond_over_rate: Mapped[float | None] = mapped_column(Float)
    cb_value: Mapped[float | None] = mapped_column(Float)
    cb_over_rate: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_cb_daily_code_date"),
    )


class CbCall(Base):
    """Convertible bond redemption/call events from Tushare cb_call API."""
    __tablename__ = "cb_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    call_type: Mapped[str | None] = mapped_column(String(16))
    is_call: Mapped[str | None] = mapped_column(String(64), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8), index=True)
    call_date: Mapped[str | None] = mapped_column(String(8))
    call_price: Mapped[float | None] = mapped_column(Float)
    call_price_tax: Mapped[float | None] = mapped_column(Float)
    call_vol: Mapped[float | None] = mapped_column(Float)
    call_amount: Mapped[float | None] = mapped_column(Float)
    payment_date: Mapped[str | None] = mapped_column(String(8))
    call_reg_date: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "call_type", name="uq_cb_call_code_ann_type"),
    )


# ── Phase 4.9: 8 new data tables ──────────────────────────────


class ShareFloat(Base):
    """Restricted share unlock schedule."""
    __tablename__ = "share_float"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    float_date: Mapped[str | None] = mapped_column(String(8), index=True)
    float_share: Mapped[float | None] = mapped_column(Float)
    float_ratio: Mapped[float | None] = mapped_column(Float)
    holder_name: Mapped[str | None] = mapped_column(String(200))
    share_type: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("ts_code", "float_date", "holder_name", "share_type",
                         name="uq_share_float"),
    )


class StkHolderTrade(Base):
    """Shareholder increase/decrease transactions."""
    __tablename__ = "stk_holdertrade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8), index=True)
    holder_name: Mapped[str | None] = mapped_column(String(200))
    holder_type: Mapped[str | None] = mapped_column(String(4))
    in_de: Mapped[str | None] = mapped_column(String(8))
    change_vol: Mapped[float | None] = mapped_column(Float)
    change_ratio: Mapped[float | None] = mapped_column(Float)
    after_share: Mapped[float | None] = mapped_column(Float)
    after_ratio: Mapped[float | None] = mapped_column(Float)
    avg_price: Mapped[float | None] = mapped_column(Float)
    total_share: Mapped[float | None] = mapped_column(Float)
    begin_date: Mapped[str | None] = mapped_column(String(8))
    close_date: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "holder_name", "in_de", "change_vol",
                         name="uq_stk_holdertrade"),
    )


class Margin(Base):
    """Daily margin trading summary by exchange."""
    __tablename__ = "margin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    exchange_id: Mapped[str | None] = mapped_column(String(8))
    rzye: Mapped[float | None] = mapped_column(Float)
    rzmre: Mapped[float | None] = mapped_column(Float)
    rzche: Mapped[float | None] = mapped_column(Float)
    rqye: Mapped[float | None] = mapped_column(Float)
    rqmcl: Mapped[float | None] = mapped_column(Float)
    rzrqye: Mapped[float | None] = mapped_column(Float)
    rqyl: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("trade_date", "exchange_id", name="uq_margin_date_exch"),
    )


class HkHold(Base):
    """Northbound/Southbound stock connect holding details."""
    __tablename__ = "hk_hold"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(16))
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(32))
    vol: Mapped[float | None] = mapped_column(Float)
    ratio: Mapped[float | None] = mapped_column(Float)
    exchange: Mapped[str | None] = mapped_column(String(4))

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "exchange",
                         name="uq_hk_hold_date_code_exch"),
    )


class TopInst(Base):
    """Dragon-tiger list institutional trading details."""
    __tablename__ = "top_inst"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    ts_code: Mapped[str | None] = mapped_column(String(16), index=True)
    exalter: Mapped[str | None] = mapped_column(String(128))
    side: Mapped[str | None] = mapped_column(String(8))
    buy: Mapped[float | None] = mapped_column(Float)
    buy_rate: Mapped[float | None] = mapped_column(Float)
    sell: Mapped[float | None] = mapped_column(Float)
    sell_rate: Mapped[float | None] = mapped_column(Float)
    net_buy: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "exalter", "side",
                         name="uq_top_inst"),
    )


class IndexDailyBasic(Base):
    """Major index daily valuation indicators (PE/PB/turnover etc)."""
    __tablename__ = "index_dailybasic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(8), index=True)
    total_mv: Mapped[float | None] = mapped_column(Float)
    float_mv: Mapped[float | None] = mapped_column(Float)
    total_share: Mapped[float | None] = mapped_column(Float)
    float_share: Mapped[float | None] = mapped_column(Float)
    free_share: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    turnover_rate_f: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    pe_ttm: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_idx_dailybasic"),
    )


class Top10FloatHolders(Base):
    """Top 10 tradable shareholders per reporting period."""
    __tablename__ = "top10_floatholders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str | None] = mapped_column(String(8), index=True)
    holder_name: Mapped[str | None] = mapped_column(String(200))
    hold_amount: Mapped[float | None] = mapped_column(Float)
    hold_ratio: Mapped[float | None] = mapped_column(Float)
    hold_float_ratio: Mapped[float | None] = mapped_column(Float)
    hold_change: Mapped[float | None] = mapped_column(Float)
    holder_type: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "holder_name",
                         name="uq_top10_float"),
    )


class StkHolderNumber(Base):
    """Shareholder count data."""
    __tablename__ = "stk_holdernumber"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    ann_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str | None] = mapped_column(String(8), index=True)
    holder_num: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "ann_date",
                         name="uq_stk_holdernumber"),
    )
