"""add stock_st adj_factor sw_daily tables

Revision ID: 06619b5940bf
Revises: 22c1d0c95d0e
Create Date: 2026-03-24 00:14:10.774961

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '06619b5940bf'
down_revision: Union[str, Sequence[str], None] = '22c1d0c95d0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('adj_factor',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('trade_date', sa.String(length=8), nullable=False),
    sa.Column('adj_factor', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'trade_date', name='uq_adj_factor_code_date')
    )
    op.create_index(op.f('ix_adj_factor_trade_date'), 'adj_factor', ['trade_date'], unique=False)
    op.create_index(op.f('ix_adj_factor_ts_code'), 'adj_factor', ['ts_code'], unique=False)

    op.create_table('stock_st',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=True),
    sa.Column('trade_date', sa.String(length=8), nullable=False),
    sa.Column('type', sa.String(length=8), nullable=True),
    sa.Column('type_name', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'trade_date', name='uq_stock_st_code_date')
    )
    op.create_index(op.f('ix_stock_st_trade_date'), 'stock_st', ['trade_date'], unique=False)
    op.create_index(op.f('ix_stock_st_ts_code'), 'stock_st', ['ts_code'], unique=False)

    op.create_table('sw_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('trade_date', sa.String(length=8), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=True),
    sa.Column('open', sa.Float(), nullable=True),
    sa.Column('low', sa.Float(), nullable=True),
    sa.Column('high', sa.Float(), nullable=True),
    sa.Column('close', sa.Float(), nullable=True),
    sa.Column('change', sa.Float(), nullable=True),
    sa.Column('pct_change', sa.Float(), nullable=True),
    sa.Column('vol', sa.Float(), nullable=True),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('pe', sa.Float(), nullable=True),
    sa.Column('pb', sa.Float(), nullable=True),
    sa.Column('float_mv', sa.Float(), nullable=True),
    sa.Column('total_mv', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'trade_date', name='uq_sw_daily_code_date')
    )
    op.create_index(op.f('ix_sw_daily_trade_date'), 'sw_daily', ['trade_date'], unique=False)
    op.create_index(op.f('ix_sw_daily_ts_code'), 'sw_daily', ['ts_code'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_sw_daily_ts_code'), table_name='sw_daily')
    op.drop_index(op.f('ix_sw_daily_trade_date'), table_name='sw_daily')
    op.drop_table('sw_daily')
    op.drop_index(op.f('ix_stock_st_ts_code'), table_name='stock_st')
    op.drop_index(op.f('ix_stock_st_trade_date'), table_name='stock_st')
    op.drop_table('stock_st')
    op.drop_index(op.f('ix_adj_factor_ts_code'), table_name='adj_factor')
    op.drop_index(op.f('ix_adj_factor_trade_date'), table_name='adj_factor')
    op.drop_table('adj_factor')
