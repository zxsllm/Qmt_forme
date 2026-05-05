"""add daily_sector_review table

Revision ID: b8a91e72f4d1
Revises: 5682e79c3237
Create Date: 2026-05-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8a91e72f4d1"
down_revision: Union[str, Sequence[str], None] = "5682e79c3237"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_sector_review",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("sector_name", sa.String(length=64), nullable=False),
        sa.Column("sector_rank", sa.Integer(), nullable=True),
        sa.Column("sector_size", sa.Integer(), nullable=True),
        sa.Column("ts_code", sa.String(length=16), nullable=True),
        sa.Column("stock_name", sa.String(length=32), nullable=True),
        sa.Column("board_count", sa.Integer(), nullable=True),
        sa.Column("days_to_board", sa.Integer(), nullable=True),
        sa.Column("limit_time", sa.String(length=16), nullable=True),
        sa.Column("float_mv", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("is_main_line", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("market_cap_tier", sa.String(length=8), nullable=True),
        sa.Column("raw_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dsr_date_source",
        "daily_sector_review",
        ["trade_date", "source"],
        unique=False,
    )
    op.create_index(
        "ix_dsr_date_sector",
        "daily_sector_review",
        ["trade_date", "sector_name"],
        unique=False,
    )
    op.create_index(
        "ix_dsr_date_tscode",
        "daily_sector_review",
        ["trade_date", "ts_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dsr_date_tscode", table_name="daily_sector_review")
    op.drop_index("ix_dsr_date_sector", table_name="daily_sector_review")
    op.drop_index("ix_dsr_date_source", table_name="daily_sector_review")
    op.drop_table("daily_sector_review")
