"""p2plus_moneyflow_news_anns_concept_tables

Revision ID: 22c1d0c95d0e
Revises: a4db372a973e
Create Date: 2026-03-23 22:09:12.413829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '22c1d0c95d0e'
down_revision: Union[str, Sequence[str], None] = 'a4db372a973e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('concept_detail',
        sa.Column('concept_code', sa.String(length=16), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('concept_name', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint('concept_code', 'ts_code')
    )
    op.create_table('concept_list',
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=True),
        sa.Column('src', sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint('code')
    )
    op.create_table('moneyflow_dc',
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('buy_sm_amount', sa.Float(), nullable=True),
        sa.Column('sell_sm_amount', sa.Float(), nullable=True),
        sa.Column('buy_md_amount', sa.Float(), nullable=True),
        sa.Column('sell_md_amount', sa.Float(), nullable=True),
        sa.Column('buy_lg_amount', sa.Float(), nullable=True),
        sa.Column('sell_lg_amount', sa.Float(), nullable=True),
        sa.Column('buy_elg_amount', sa.Float(), nullable=True),
        sa.Column('sell_elg_amount', sa.Float(), nullable=True),
        sa.Column('net_mf_amount', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('ts_code', 'trade_date')
    )
    op.create_table('stock_anns',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('ann_date', sa.String(length=8), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stock_anns_ann_date', 'stock_anns', ['ann_date'])
    op.create_index('ix_stock_anns_ts_code', 'stock_anns', ['ts_code'])
    op.create_table('stock_news',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('datetime', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('channels', sa.String(length=128), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_stock_news_datetime', 'stock_news', ['datetime'])


def downgrade() -> None:
    op.drop_index('ix_stock_news_datetime', table_name='stock_news')
    op.drop_table('stock_news')
    op.drop_index('ix_stock_anns_ts_code', table_name='stock_anns')
    op.drop_index('ix_stock_anns_ann_date', table_name='stock_anns')
    op.drop_table('stock_anns')
    op.drop_table('moneyflow_dc')
    op.drop_table('concept_list')
    op.drop_table('concept_detail')
