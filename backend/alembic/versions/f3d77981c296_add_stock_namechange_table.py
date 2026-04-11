"""add stock_namechange table

Revision ID: f3d77981c296
Revises: 4c7b26b819dd
Create Date: 2026-04-08 05:40:21.488135

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3d77981c296'
down_revision: Union[str, Sequence[str], None] = '4c7b26b819dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('stock_namechange',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts_code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=True),
    sa.Column('start_date', sa.String(length=8), nullable=True),
    sa.Column('end_date', sa.String(length=8), nullable=True),
    sa.Column('ann_date', sa.String(length=8), nullable=True),
    sa.Column('change_reason', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ts_code', 'start_date', name='uq_namechange_code_start')
    )
    op.create_index(op.f('ix_stock_namechange_ann_date'), 'stock_namechange', ['ann_date'], unique=False)
    op.create_index(op.f('ix_stock_namechange_ts_code'), 'stock_namechange', ['ts_code'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_stock_namechange_ts_code'), table_name='stock_namechange')
    op.drop_index(op.f('ix_stock_namechange_ann_date'), table_name='stock_namechange')
    op.drop_table('stock_namechange')
