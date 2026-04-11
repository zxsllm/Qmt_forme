"""add dividend table

Revision ID: 4c7b26b819dd
Revises: 40ed3b843e8d
Create Date: 2026-04-08 05:19:49.840615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4c7b26b819dd'
down_revision: Union[str, Sequence[str], None] = '40ed3b843e8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dividend',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(16), nullable=False),
        sa.Column('end_date', sa.String(8), nullable=False),
        sa.Column('ann_date', sa.String(8)),
        sa.Column('div_proc', sa.String(20)),
        sa.Column('stk_div', sa.Float),
        sa.Column('cash_div', sa.Float),
        sa.Column('cash_div_tax', sa.Float),
        sa.Column('record_date', sa.String(8)),
        sa.Column('ex_date', sa.String(8)),
        sa.Column('pay_date', sa.String(8)),
        sa.UniqueConstraint('ts_code', 'end_date', 'div_proc', name='uq_dividend_code_date_proc'),
    )
    op.create_index('idx_dividend_ts_code', 'dividend', ['ts_code'])
    op.create_index('idx_dividend_end_date', 'dividend', ['end_date'])


def downgrade() -> None:
    op.drop_table('dividend')
