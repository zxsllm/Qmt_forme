"""add daily_review and daily_plan tables

Revision ID: 9dd4ee2ba5bd
Revises: f3d77981c296
Create Date: 2026-04-11 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9dd4ee2ba5bd"
down_revision: Union[str, None] = "f3d77981c296"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # daily_review 表
    op.create_table(
        "daily_review",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("trade_date", sa.String(8), unique=True, index=True, nullable=False),
        # 大盘指数
        sa.Column("sh_close", sa.Float(), nullable=True),
        sa.Column("sh_pct_chg", sa.Float(), nullable=True),
        sa.Column("sz_close", sa.Float(), nullable=True),
        sa.Column("sz_pct_chg", sa.Float(), nullable=True),
        sa.Column("cy_close", sa.Float(), nullable=True),
        sa.Column("cy_pct_chg", sa.Float(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("amount_chg_pct", sa.Float(), nullable=True),
        # 情绪温度计
        sa.Column("temperature", sa.String(8), nullable=True),
        sa.Column("limit_up_count", sa.Integer(), nullable=True),
        sa.Column("limit_down_count", sa.Integer(), nullable=True),
        sa.Column("broken_count", sa.Integer(), nullable=True),
        sa.Column("seal_rate", sa.Float(), nullable=True),
        sa.Column("max_board", sa.Integer(), nullable=True),
        sa.Column("up_count", sa.Integer(), nullable=True),
        sa.Column("down_count", sa.Integer(), nullable=True),
        sa.Column("up_down_ratio", sa.Float(), nullable=True),
        # 资金面
        sa.Column("margin_balance", sa.Float(), nullable=True),
        sa.Column("margin_net_buy", sa.Float(), nullable=True),
        sa.Column("hot_money_net", sa.Float(), nullable=True),
        sa.Column("inst_net_buy", sa.Float(), nullable=True),
        # 结构化JSON
        sa.Column("top_sectors_json", sa.Text(), server_default="[]"),
        sa.Column("bottom_sectors_json", sa.Text(), server_default="[]"),
        sa.Column("dragon_stocks_json", sa.Text(), server_default="[]"),
        sa.Column("hot_money_json", sa.Text(), server_default="[]"),
        sa.Column("limit_ladder_json", sa.Text(), server_default="[]"),
        sa.Column("risk_alerts_json", sa.Text(), server_default="[]"),
        # 文本字段
        sa.Column("market_summary", sa.Text(), server_default=""),
        sa.Column("sector_analysis", sa.Text(), server_default=""),
        sa.Column("sentiment_narrative", sa.Text(), server_default=""),
        sa.Column("board_play_summary", sa.Text(), server_default=""),
        sa.Column("swing_trade_summary", sa.Text(), server_default=""),
        sa.Column("value_invest_summary", sa.Text(), server_default=""),
        sa.Column("strategy_conclusion", sa.Text(), server_default=""),
        sa.Column("risk_summary", sa.Text(), server_default=""),
        sa.Column("dominant_strategy", sa.String(16), nullable=True),
        sa.Column("strategy_switch_signal", sa.Text(), server_default=""),
        # 时间戳
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("NOW()"),
        ),
    )

    # 36维市场特征向量列（pgvector）
    op.execute(
        "ALTER TABLE daily_review ADD COLUMN market_feature_vector vector(36)"
    )

    # daily_plan 表
    op.create_table(
        "daily_plan",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("trade_date", sa.String(8), unique=True, index=True, nullable=False),
        # 隔夜环境
        sa.Column("us_sp500_pct", sa.Float(), nullable=True),
        sa.Column("us_nasdaq_pct", sa.Float(), nullable=True),
        sa.Column("a50_night_pct", sa.Float(), nullable=True),
        sa.Column("hk_hsi_pct", sa.Float(), nullable=True),
        # 预判
        sa.Column("predicted_temperature", sa.String(8), nullable=True),
        sa.Column("predicted_direction", sa.String(8), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        # 结构化JSON
        sa.Column("watch_sectors_json", sa.Text(), server_default="[]"),
        sa.Column("watch_stocks_json", sa.Text(), server_default="[]"),
        sa.Column("avoid_sectors_json", sa.Text(), server_default="[]"),
        sa.Column("key_events_json", sa.Text(), server_default="[]"),
        sa.Column("auction_signals_json", sa.Text(), server_default="[]"),
        sa.Column("strategy_weights_json", sa.Text(), server_default="{}"),
        # 操作计划JSON
        sa.Column("position_plan_json", sa.Text(), server_default="{}"),
        sa.Column("entry_plan_json", sa.Text(), server_default="[]"),
        sa.Column("exit_plan_json", sa.Text(), server_default="[]"),
        # 文本字段
        sa.Column("overnight_summary", sa.Text(), server_default=""),
        sa.Column("board_play_plan", sa.Text(), server_default=""),
        sa.Column("swing_trade_plan", sa.Text(), server_default=""),
        sa.Column("value_invest_plan", sa.Text(), server_default=""),
        sa.Column("key_logic", sa.Text(), server_default=""),
        sa.Column("risk_notes", sa.Text(), server_default=""),
        # 回溯验证
        sa.Column("actual_result", sa.String(8), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=True),
        sa.Column("retrospect_note", sa.Text(), server_default=""),
        # 时间戳
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("NOW()"),
        ),
    )

    # 16维环境特征向量列（pgvector）
    op.execute(
        "ALTER TABLE daily_plan ADD COLUMN env_feature_vector vector(16)"
    )

    # 向量索引（数据量小，IVFFlat lists=1 最优）
    op.execute("""
        CREATE INDEX ix_daily_review_market_vec
        ON daily_review USING ivfflat (market_feature_vector vector_cosine_ops)
        WITH (lists = 1)
    """)
    op.execute("""
        CREATE INDEX ix_daily_plan_env_vec
        ON daily_plan USING ivfflat (env_feature_vector vector_cosine_ops)
        WITH (lists = 1)
    """)


def downgrade() -> None:
    op.drop_table("daily_plan")
    op.drop_table("daily_review")
