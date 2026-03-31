"""add cb_basic cb_daily cb_call tables

Revision ID: 2a146f5a0630
Revises: 9c43c6c8212d
Create Date: 2026-03-31 23:40:03.147526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '2a146f5a0630'
down_revision: Union[str, Sequence[str], None] = '9c43c6c8212d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cb_basic',
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('bond_short_name', sa.String(length=32), nullable=True),
    sa.Column('stk_code', sa.String(length=16), nullable=True),
    sa.Column('stk_short_name', sa.String(length=32), nullable=True),
    sa.Column('maturity', sa.Float(), nullable=True),
    sa.Column('maturity_date', sa.String(length=8), nullable=True),
    sa.Column('list_date', sa.String(length=8), nullable=True),
    sa.Column('delist_date', sa.String(length=8), nullable=True),
    sa.Column('exchange', sa.String(length=8), nullable=True),
    sa.Column('conv_start_date', sa.String(length=8), nullable=True),
    sa.Column('conv_end_date', sa.String(length=8), nullable=True),
    sa.Column('conv_price', sa.Float(), nullable=True),
    sa.Column('first_conv_price', sa.Float(), nullable=True),
    sa.Column('issue_size', sa.Float(), nullable=True),
    sa.Column('remain_size', sa.Float(), nullable=True),
    sa.Column('call_clause', sa.Text(), nullable=True),
    sa.Column('put_clause', sa.Text(), nullable=True),
    sa.Column('reset_clause', sa.Text(), nullable=True),
    sa.Column('conv_clause', sa.Text(), nullable=True),
    sa.Column('par', sa.Float(), nullable=True),
    sa.Column('issue_price', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('ts_code')
    )
    op.create_index(op.f('ix_cb_basic_stk_code'), 'cb_basic', ['stk_code'], unique=False)

    op.create_table('cb_call',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('call_type', sa.String(length=16), nullable=True),
    sa.Column('is_call', sa.String(length=64), nullable=True),
    sa.Column('ann_date', sa.String(length=8), nullable=True),
    sa.Column('call_date', sa.String(length=8), nullable=True),
    sa.Column('call_price', sa.Float(), nullable=True),
    sa.Column('call_price_tax', sa.Float(), nullable=True),
    sa.Column('call_vol', sa.Float(), nullable=True),
    sa.Column('call_amount', sa.Float(), nullable=True),
    sa.Column('payment_date', sa.String(length=8), nullable=True),
    sa.Column('call_reg_date', sa.String(length=8), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'ann_date', 'call_type', name='uq_cb_call_code_ann_type')
    )
    op.create_index(op.f('ix_cb_call_ann_date'), 'cb_call', ['ann_date'], unique=False)
    op.create_index(op.f('ix_cb_call_is_call'), 'cb_call', ['is_call'], unique=False)
    op.create_index(op.f('ix_cb_call_ts_code'), 'cb_call', ['ts_code'], unique=False)

    op.create_table('cb_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('trade_date', sa.String(length=8), nullable=False),
    sa.Column('pre_close', sa.Float(), nullable=True),
    sa.Column('open', sa.Float(), nullable=True),
    sa.Column('high', sa.Float(), nullable=True),
    sa.Column('low', sa.Float(), nullable=True),
    sa.Column('close', sa.Float(), nullable=True),
    sa.Column('change', sa.Float(), nullable=True),
    sa.Column('pct_chg', sa.Float(), nullable=True),
    sa.Column('vol', sa.Float(), nullable=True),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('bond_value', sa.Float(), nullable=True),
    sa.Column('bond_over_rate', sa.Float(), nullable=True),
    sa.Column('cb_value', sa.Float(), nullable=True),
    sa.Column('cb_over_rate', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'trade_date', name='uq_cb_daily_code_date')
    )
    op.create_index(op.f('ix_cb_daily_trade_date'), 'cb_daily', ['trade_date'], unique=False)
    op.create_index(op.f('ix_cb_daily_ts_code'), 'cb_daily', ['ts_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cb_daily_ts_code'), table_name='cb_daily')
    op.drop_index(op.f('ix_cb_daily_trade_date'), table_name='cb_daily')
    op.drop_table('cb_daily')
    op.drop_index(op.f('ix_cb_call_ts_code'), table_name='cb_call')
    op.drop_index(op.f('ix_cb_call_is_call'), table_name='cb_call')
    op.drop_index(op.f('ix_cb_call_ann_date'), table_name='cb_call')
    op.drop_table('cb_call')
    op.drop_index(op.f('ix_cb_basic_stk_code'), table_name='cb_basic')
    op.drop_table('cb_basic')
