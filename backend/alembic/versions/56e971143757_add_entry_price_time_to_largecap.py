"""add entry_price and entry_time to largecap alerts

Revision ID: 56e971143757
Revises: 6f90928dab46
Create Date: 2026-04-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '56e971143757'
down_revision: Union[str, Sequence[str], None] = '6f90928dab46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monitor_largecap_alerts',
                  sa.Column('entry_price', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts',
                  sa.Column('entry_time', sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column('monitor_largecap_alerts', 'entry_time')
    op.drop_column('monitor_largecap_alerts', 'entry_price')
