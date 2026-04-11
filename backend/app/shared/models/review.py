"""每日复盘与早盘计划 ORM 模型

daily_review: 收盘复盘报告（15:30后生成）
daily_plan:   开盘前早盘计划（08:00前生成）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # pgvector 未安装时不阻塞其他模块加载


class DailyReview(Base):
    """每日收盘复盘报告"""

    __tablename__ = "daily_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), unique=True, index=True)

    # ── 大盘指数 ──
    sh_close: Mapped[float | None] = mapped_column(Float)
    sh_pct_chg: Mapped[float | None] = mapped_column(Float)
    sz_close: Mapped[float | None] = mapped_column(Float)
    sz_pct_chg: Mapped[float | None] = mapped_column(Float)
    cy_close: Mapped[float | None] = mapped_column(Float)
    cy_pct_chg: Mapped[float | None] = mapped_column(Float)
    total_amount: Mapped[float | None] = mapped_column(Float)  # 两市成交额(亿)
    amount_chg_pct: Mapped[float | None] = mapped_column(Float)  # 成交额环比%

    # ── 情绪温度计 ──
    temperature: Mapped[str | None] = mapped_column(String(8))  # 极热/偏热/中性/偏冷/冰点
    limit_up_count: Mapped[int | None] = mapped_column(Integer)
    limit_down_count: Mapped[int | None] = mapped_column(Integer)
    broken_count: Mapped[int | None] = mapped_column(Integer)
    seal_rate: Mapped[float | None] = mapped_column(Float)  # 封板率%
    max_board: Mapped[int | None] = mapped_column(Integer)  # 最高连板
    up_count: Mapped[int | None] = mapped_column(Integer)  # 上涨家数
    down_count: Mapped[int | None] = mapped_column(Integer)  # 下跌家数
    up_down_ratio: Mapped[float | None] = mapped_column(Float)

    # ── 资金面 ──
    margin_balance: Mapped[float | None] = mapped_column(Float)  # 两融余额(亿)
    margin_net_buy: Mapped[float | None] = mapped_column(Float)  # 融资净买入(亿)
    hot_money_net: Mapped[float | None] = mapped_column(Float)  # 游资净买入(亿)
    inst_net_buy: Mapped[float | None] = mapped_column(Float)  # 机构净买入(亿)

    # ── 结构化JSON ──
    top_sectors_json: Mapped[str] = mapped_column(Text, default="[]")
    bottom_sectors_json: Mapped[str] = mapped_column(Text, default="[]")
    dragon_stocks_json: Mapped[str] = mapped_column(Text, default="[]")
    hot_money_json: Mapped[str] = mapped_column(Text, default="[]")
    limit_ladder_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_alerts_json: Mapped[str] = mapped_column(Text, default="[]")

    # ── 文本字段（模板拼接 → 后续 Claude CLI 增强） ──
    market_summary: Mapped[str] = mapped_column(Text, default="")
    sector_analysis: Mapped[str] = mapped_column(Text, default="")
    sentiment_narrative: Mapped[str] = mapped_column(Text, default="")
    board_play_summary: Mapped[str] = mapped_column(Text, default="")
    swing_trade_summary: Mapped[str] = mapped_column(Text, default="")
    value_invest_summary: Mapped[str] = mapped_column(Text, default="")
    strategy_conclusion: Mapped[str] = mapped_column(Text, default="")
    risk_summary: Mapped[str] = mapped_column(Text, default="")
    dominant_strategy: Mapped[str | None] = mapped_column(String(16))
    strategy_switch_signal: Mapped[str] = mapped_column(Text, default="")

    # ── 数值特征向量（36维，纯数学标准化，无需模型） ──
    # pgvector 未安装时该列不生效，需 CREATE EXTENSION vector
    if Vector is not None:
        market_feature_vector = mapped_column(Vector(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )


class DailyPlan(Base):
    """每日开盘前早盘计划"""

    __tablename__ = "daily_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(8), unique=True, index=True)

    # ── 隔夜环境 ──
    us_sp500_pct: Mapped[float | None] = mapped_column(Float)
    us_nasdaq_pct: Mapped[float | None] = mapped_column(Float)
    a50_night_pct: Mapped[float | None] = mapped_column(Float)
    hk_hsi_pct: Mapped[float | None] = mapped_column(Float)

    # ── 预判 ──
    predicted_temperature: Mapped[str | None] = mapped_column(String(8))
    predicted_direction: Mapped[str | None] = mapped_column(String(8))
    confidence_score: Mapped[float | None] = mapped_column(Float)

    # ── 结构化JSON ──
    watch_sectors_json: Mapped[str] = mapped_column(Text, default="[]")
    watch_stocks_json: Mapped[str] = mapped_column(Text, default="[]")
    avoid_sectors_json: Mapped[str] = mapped_column(Text, default="[]")
    key_events_json: Mapped[str] = mapped_column(Text, default="[]")
    auction_signals_json: Mapped[str] = mapped_column(Text, default="[]")
    strategy_weights_json: Mapped[str] = mapped_column(Text, default="{}")

    # ── 操作计划JSON（完整版） ──
    position_plan_json: Mapped[str] = mapped_column(Text, default="{}")
    entry_plan_json: Mapped[str] = mapped_column(Text, default="[]")
    exit_plan_json: Mapped[str] = mapped_column(Text, default="[]")

    # ── 文本字段 ──
    overnight_summary: Mapped[str] = mapped_column(Text, default="")
    board_play_plan: Mapped[str] = mapped_column(Text, default="")
    swing_trade_plan: Mapped[str] = mapped_column(Text, default="")
    value_invest_plan: Mapped[str] = mapped_column(Text, default="")
    key_logic: Mapped[str] = mapped_column(Text, default="")
    risk_notes: Mapped[str] = mapped_column(Text, default="")

    # ── 回溯验证 ──
    actual_result: Mapped[str | None] = mapped_column(String(8))  # 正确/部分正确/错误
    accuracy_score: Mapped[float | None] = mapped_column(Float)
    retrospect_note: Mapped[str] = mapped_column(Text, default="")

    # ── 环境特征向量（16维） ──
    if Vector is not None:
        env_feature_vector = mapped_column(Vector(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("NOW()")
    )
