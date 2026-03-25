"""add stk_auction eco_cal moneyflow_ind_ths tables

Revision ID: da4919e644e3
Revises: 06619b5940bf
Create Date: 2026-03-25 10:38:53.401415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'da4919e644e3'
down_revision: Union[str, Sequence[str], None] = '06619b5940bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('eco_cal',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.String(length=8), nullable=True),
        sa.Column('time', sa.String(length=8), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('country', sa.String(length=16), nullable=True),
        sa.Column('event', sa.Text(), nullable=True),
        sa.Column('value', sa.String(length=32), nullable=True),
        sa.Column('pre_value', sa.String(length=32), nullable=True),
        sa.Column('fore_value', sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', 'time', 'event', name='uq_eco_cal_date_time_event')
    )
    op.create_index(op.f('ix_eco_cal_date'), 'eco_cal', ['date'], unique=False)

    op.create_table('moneyflow_ind_ths',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('industry', sa.String(length=32), nullable=True),
        sa.Column('lead_stock', sa.String(length=16), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('pct_change', sa.Float(), nullable=True),
        sa.Column('company_num', sa.Integer(), nullable=True),
        sa.Column('pct_change_stock', sa.Float(), nullable=True),
        sa.Column('close_price', sa.Float(), nullable=True),
        sa.Column('net_buy_amount', sa.Float(), nullable=True),
        sa.Column('net_sell_amount', sa.Float(), nullable=True),
        sa.Column('net_amount', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ts_code', 'trade_date', name='uq_mf_ind_ths_code_date')
    )
    op.create_index(op.f('ix_moneyflow_ind_ths_trade_date'), 'moneyflow_ind_ths', ['trade_date'], unique=False)
    op.create_index(op.f('ix_moneyflow_ind_ths_ts_code'), 'moneyflow_ind_ths', ['ts_code'], unique=False)

    op.create_table('stk_auction',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('vol', sa.Float(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('pre_close', sa.Float(), nullable=True),
        sa.Column('turnover_rate', sa.Float(), nullable=True),
        sa.Column('volume_ratio', sa.Float(), nullable=True),
        sa.Column('float_share', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ts_code', 'trade_date', name='uq_stk_auction_code_date')
    )
    op.create_index(op.f('ix_stk_auction_trade_date'), 'stk_auction', ['trade_date'], unique=False)
    op.create_index(op.f('ix_stk_auction_ts_code'), 'stk_auction', ['ts_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stk_auction_ts_code'), table_name='stk_auction')
    op.drop_index(op.f('ix_stk_auction_trade_date'), table_name='stk_auction')
    op.drop_table('stk_auction')
    op.drop_index(op.f('ix_moneyflow_ind_ths_ts_code'), table_name='moneyflow_ind_ths')
    op.drop_index(op.f('ix_moneyflow_ind_ths_trade_date'), table_name='moneyflow_ind_ths')
    op.drop_table('moneyflow_ind_ths')
    op.drop_index(op.f('ix_eco_cal_date'), table_name='eco_cal')
    op.drop_table('eco_cal')
