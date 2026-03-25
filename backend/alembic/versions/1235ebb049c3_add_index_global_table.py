"""add index_global table

Revision ID: 1235ebb049c3
Revises: da4919e644e3
Create Date: 2026-03-25 21:20:58.170614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1235ebb049c3'
down_revision: Union[str, Sequence[str], None] = 'da4919e644e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('index_global',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('trade_date', sa.String(length=8), nullable=False),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('pre_close', sa.Float(), nullable=True),
        sa.Column('change', sa.Float(), nullable=True),
        sa.Column('pct_chg', sa.Float(), nullable=True),
        sa.Column('vol', sa.Float(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ts_code', 'trade_date', name='uq_index_global_code_date')
    )
    op.create_index(op.f('ix_index_global_trade_date'), 'index_global', ['trade_date'], unique=False)
    op.create_index(op.f('ix_index_global_ts_code'), 'index_global', ['ts_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_index_global_ts_code'), table_name='index_global')
    op.drop_index(op.f('ix_index_global_trade_date'), table_name='index_global')
    op.drop_table('index_global')
