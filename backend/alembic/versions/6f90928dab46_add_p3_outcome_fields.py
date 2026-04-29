"""add p3 outcome fields to monitor tables

Revision ID: 6f90928dab46
Revises: 66fd8acc67c2
Create Date: 2026-04-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6f90928dab46'
down_revision: Union[str, Sequence[str], None] = '66fd8acc67c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- monitor_events: add 60m fields + close_pos + path_label --
    op.add_column('monitor_events', sa.Column('ret_60m', sa.Float(), nullable=True))
    op.add_column('monitor_events', sa.Column('max_up_60m', sa.Float(), nullable=True))
    op.add_column('monitor_events', sa.Column('max_down_60m', sa.Float(), nullable=True))
    op.add_column('monitor_events', sa.Column('close_pos_30m', sa.Float(), nullable=True))
    op.add_column('monitor_events', sa.Column('close_pos_60m', sa.Float(), nullable=True))
    op.add_column('monitor_events', sa.Column('path_label', sa.String(20), nullable=True))

    # -- monitor_largecap_alerts: add full outcome suite --
    op.add_column('monitor_largecap_alerts', sa.Column('ret_60m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('max_up_30m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('max_down_30m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('max_up_60m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('max_down_60m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('close_pos_30m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('close_pos_60m', sa.Float(), nullable=True))
    op.add_column('monitor_largecap_alerts', sa.Column('path_label', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('monitor_largecap_alerts', 'path_label')
    op.drop_column('monitor_largecap_alerts', 'close_pos_60m')
    op.drop_column('monitor_largecap_alerts', 'close_pos_30m')
    op.drop_column('monitor_largecap_alerts', 'max_down_60m')
    op.drop_column('monitor_largecap_alerts', 'max_up_60m')
    op.drop_column('monitor_largecap_alerts', 'max_down_30m')
    op.drop_column('monitor_largecap_alerts', 'max_up_30m')
    op.drop_column('monitor_largecap_alerts', 'ret_60m')

    op.drop_column('monitor_events', 'path_label')
    op.drop_column('monitor_events', 'close_pos_60m')
    op.drop_column('monitor_events', 'close_pos_30m')
    op.drop_column('monitor_events', 'max_down_60m')
    op.drop_column('monitor_events', 'max_up_60m')
    op.drop_column('monitor_events', 'ret_60m')
