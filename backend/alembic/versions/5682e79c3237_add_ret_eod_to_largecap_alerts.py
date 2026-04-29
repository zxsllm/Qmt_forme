"""add ret_eod to largecap alerts

Revision ID: 5682e79c3237
Revises: 56e971143757
Create Date: 2026-04-17 05:01:59.617643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5682e79c3237'
down_revision: Union[str, Sequence[str], None] = '56e971143757'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monitor_largecap_alerts',
                  sa.Column('ret_eod', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('monitor_largecap_alerts', 'ret_eod')
