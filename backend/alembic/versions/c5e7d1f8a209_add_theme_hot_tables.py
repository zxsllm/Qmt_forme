"""add theme hot tables: kpl_list, ths_hot, moneyflow_cnt_ths, dc_index

Revision ID: c5e7d1f8a209
Revises: b8a91e72f4d1
Create Date: 2026-05-08 20:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e7d1f8a209'
down_revision: Union[str, Sequence[str], None] = 'b8a91e72f4d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # kpl_list: 开盘啦榜单（次日 08:30 出，含题材 / 连板状态 / 主力净额）
    op.create_table(
        'kpl_list',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=32), nullable=True),
        sa.Column('lu_time', sa.String(length=16), nullable=True),
        sa.Column('ld_time', sa.String(length=16), nullable=True),
        sa.Column('open_time', sa.String(length=16), nullable=True),
        sa.Column('last_time', sa.String(length=16), nullable=True),
        sa.Column('lu_desc', sa.Text(), nullable=True),
        sa.Column('tag', sa.String(length=32), nullable=True),
        sa.Column('theme', sa.String(length=128), nullable=True),
        sa.Column('net_change', sa.Float(), nullable=True),
        sa.Column('bid_amount', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('bid_change', sa.Float(), nullable=True),
        sa.Column('bid_turnover', sa.Float(), nullable=True),
        sa.Column('lu_bid_vol', sa.Float(), nullable=True),
        sa.Column('pct_chg', sa.Float(), nullable=True),
        sa.Column('bid_pct_chg', sa.Float(), nullable=True),
        sa.Column('rzrq', sa.String(length=8), nullable=True),
        sa.Column('limit_order', sa.Float(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('turnover_rate', sa.Float(), nullable=True),
        sa.Column('free_float', sa.Float(), nullable=True),
        sa.Column('lu_limit_order', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_date', 'ts_code', 'tag', name='uq_kpl_list_dtct'),
    )
    op.create_index(op.f('ix_kpl_list_trade_date'), 'kpl_list', ['trade_date'], unique=False)
    op.create_index(op.f('ix_kpl_list_ts_code'), 'kpl_list', ['ts_code'], unique=False)
    op.create_index(op.f('ix_kpl_list_theme'), 'kpl_list', ['theme'], unique=False)

    # ths_hot: 同花顺热榜（盘后多次 + 22:30 完整版，is_new=Y/N 区分两个版本）
    op.create_table(
        'ths_hot',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('data_type', sa.String(length=32), nullable=True),
        sa.Column('ts_code', sa.String(length=16), nullable=True),
        sa.Column('ts_name', sa.String(length=64), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('pct_change', sa.Float(), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('concept', sa.Text(), nullable=True),
        sa.Column('rank_reason', sa.Text(), nullable=True),
        sa.Column('hot', sa.Float(), nullable=True),
        sa.Column('rank_time', sa.String(length=32), nullable=True),
        sa.Column('is_new', sa.String(length=2), nullable=True, server_default='Y'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_date', 'ts_code', 'data_type', 'is_new', name='uq_ths_hot_dtcdi'),
    )
    op.create_index(op.f('ix_ths_hot_trade_date'), 'ths_hot', ['trade_date'], unique=False)
    op.create_index(op.f('ix_ths_hot_ts_code'), 'ths_hot', ['ts_code'], unique=False)
    op.create_index(op.f('ix_ths_hot_data_type'), 'ths_hot', ['data_type'], unique=False)

    # moneyflow_cnt_ths: 同花顺概念板块资金流（盘后即出）
    op.create_table(
        'moneyflow_cnt_ths',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=True),
        sa.Column('lead_stock', sa.String(length=32), nullable=True),
        sa.Column('close_price', sa.Float(), nullable=True),
        sa.Column('pct_change', sa.Float(), nullable=True),
        sa.Column('index_close', sa.Float(), nullable=True),
        sa.Column('company_num', sa.Integer(), nullable=True),
        sa.Column('pct_change_stock', sa.Float(), nullable=True),
        sa.Column('net_buy_amount', sa.Float(), nullable=True),
        sa.Column('net_sell_amount', sa.Float(), nullable=True),
        sa.Column('net_amount', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_date', 'ts_code', name='uq_moneyflow_cnt_ths_dtc'),
    )
    op.create_index(op.f('ix_moneyflow_cnt_ths_trade_date'), 'moneyflow_cnt_ths', ['trade_date'], unique=False)
    op.create_index(op.f('ix_moneyflow_cnt_ths_ts_code'), 'moneyflow_cnt_ths', ['ts_code'], unique=False)

    # dc_index: 东财概念板块日行情（idx_type 区分 行业/概念/地域）
    op.create_table(
        'dc_index',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=True),
        sa.Column('leading', sa.String(length=32), nullable=True),
        sa.Column('leading_code', sa.String(length=16), nullable=True),
        sa.Column('pct_change', sa.Float(), nullable=True),
        sa.Column('leading_pct', sa.Float(), nullable=True),
        sa.Column('total_mv', sa.Float(), nullable=True),
        sa.Column('turnover_rate', sa.Float(), nullable=True),
        sa.Column('up_num', sa.Integer(), nullable=True),
        sa.Column('down_num', sa.Integer(), nullable=True),
        sa.Column('idx_type', sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trade_date', 'ts_code', name='uq_dc_index_dtc'),
    )
    op.create_index(op.f('ix_dc_index_trade_date'), 'dc_index', ['trade_date'], unique=False)
    op.create_index(op.f('ix_dc_index_ts_code'), 'dc_index', ['ts_code'], unique=False)
    op.create_index(op.f('ix_dc_index_idx_type'), 'dc_index', ['idx_type'], unique=False)


def downgrade() -> None:
    for t in ['dc_index', 'moneyflow_cnt_ths', 'ths_hot', 'kpl_list']:
        op.drop_table(t)
