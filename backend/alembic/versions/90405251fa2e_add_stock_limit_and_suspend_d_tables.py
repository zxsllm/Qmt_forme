"""add stock_limit and suspend_d tables

Revision ID: 90405251fa2e
Revises: a008f95a8b9a
Create Date: 2026-03-22 19:33:45.386512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '90405251fa2e'
down_revision: Union[str, Sequence[str], None] = 'a008f95a8b9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stock_limit',
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('up_limit', sa.Float(), nullable=True),
        sa.Column('down_limit', sa.Float(), nullable=True),
        sa.Column('pre_close', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('ts_code', 'trade_date')
    )
    op.create_table('suspend_d',
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('suspend_type', sa.String(length=4), nullable=True),
        sa.Column('suspend_timing', sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint('ts_code', 'trade_date')
    )


def downgrade() -> None:
    op.drop_table('suspend_d')
    op.drop_table('stock_limit')
