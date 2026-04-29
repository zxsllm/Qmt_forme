"""add monitor_events and monitor_largecap_alerts tables

Revision ID: 1434d56499dd
Revises: 57f021d72ed2
Create Date: 2026-04-15 00:32:06.316370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1434d56499dd'
down_revision: Union[str, Sequence[str], None] = '57f021d72ed2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create monitor_events and monitor_largecap_alerts tables."""
    op.create_table('monitor_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_date', sa.String(length=10), nullable=False),
        sa.Column('event_ts', sa.Float(), nullable=False),
        sa.Column('event_time', sa.String(length=8), nullable=False),
        sa.Column('index_code', sa.String(length=16), nullable=False),
        sa.Column('index_name', sa.String(length=32), nullable=True),
        sa.Column('window', sa.String(length=8), nullable=False),
        sa.Column('delta_pct', sa.Float(), nullable=False),
        sa.Column('price_now', sa.Float(), nullable=True),
        sa.Column('price_then', sa.Float(), nullable=True),
        sa.Column('pattern', sa.String(length=32), nullable=True),
        sa.Column('level', sa.String(length=8), nullable=True),
        sa.Column('event_score', sa.Integer(), nullable=True),
        sa.Column('watchlist_hits_json', sa.Text(), nullable=True),
        sa.Column('position_hits_json', sa.Text(), nullable=True),
        sa.Column('hit_count', sa.Integer(), nullable=True),
        sa.Column('top_sectors_json', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('action_hint', sa.String(length=128), nullable=True),
        sa.Column('ret_5m', sa.Float(), nullable=True),
        sa.Column('ret_15m', sa.Float(), nullable=True),
        sa.Column('ret_30m', sa.Float(), nullable=True),
        sa.Column('max_move_30m', sa.Float(), nullable=True),
        sa.Column('min_move_30m', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_date', 'event_ts', 'index_code', 'window', name='uq_monitor_event'),
    )
    op.create_index(op.f('ix_monitor_events_event_date'), 'monitor_events', ['event_date'], unique=False)

    op.create_table('monitor_largecap_alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_date', sa.String(length=10), nullable=False),
        sa.Column('event_ts', sa.Float(), nullable=False),
        sa.Column('event_time', sa.String(length=8), nullable=False),
        sa.Column('ts_code', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=32), nullable=True),
        sa.Column('price_now', sa.Float(), nullable=True),
        sa.Column('price_yesterday', sa.Float(), nullable=True),
        sa.Column('price_chg_pct', sa.Float(), nullable=True),
        sa.Column('vol_now', sa.Float(), nullable=True),
        sa.Column('vol_yesterday', sa.Float(), nullable=True),
        sa.Column('vol_ratio', sa.Float(), nullable=True),
        sa.Column('circ_mv_yi', sa.Float(), nullable=True),
        sa.Column('sector', sa.String(length=32), nullable=True),
        sa.Column('sector_strong', sa.Boolean(), nullable=True),
        sa.Column('in_watchlist', sa.Boolean(), nullable=True),
        sa.Column('in_position', sa.Boolean(), nullable=True),
        sa.Column('ret_5m', sa.Float(), nullable=True),
        sa.Column('ret_15m', sa.Float(), nullable=True),
        sa.Column('ret_30m', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_date', 'event_ts', 'ts_code', name='uq_monitor_largecap'),
    )
    op.create_index(op.f('ix_monitor_largecap_alerts_event_date'), 'monitor_largecap_alerts', ['event_date'], unique=False)


def downgrade() -> None:
    """Drop monitor tables."""
    op.drop_index(op.f('ix_monitor_largecap_alerts_event_date'), table_name='monitor_largecap_alerts')
    op.drop_table('monitor_largecap_alerts')
    op.drop_index(op.f('ix_monitor_events_event_date'), table_name='monitor_events')
    op.drop_table('monitor_events')
