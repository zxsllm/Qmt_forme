"""add ret_eod to monitor_events

Revision ID: 66fd8acc67c2
Revises: 1434d56499dd
Create Date: 2026-04-15 00:50:27.580786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '66fd8acc67c2'
down_revision: Union[str, Sequence[str], None] = '1434d56499dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monitor_events', sa.Column('ret_eod', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('monitor_events', 'ret_eod')
