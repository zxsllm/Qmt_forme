"""add pattern OMS fields (lot architecture + sell_anchor metadata)

Revision ID: a1b2c3d4e5f6
Revises: d6f8e2a3b410
Create Date: 2026-05-14 10:00:00.000000

Adds OMS fields to support Pattern1/2 live trading:
- sim_orders: sell_anchor metadata + pick_kind/pick_role + metadata JSONB
- sim_positions: switch PK from ts_code to lot_id (UUID); add lot/sell_anchor fields

Note: existing sim_positions rows are migrated by generating a UUID lot_id per row
(no data loss for legacy aggregated positions; they keep behaving as single-lot).
"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd6f8e2a3b410'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- sim_orders: add pattern-aware columns ---
    op.add_column('sim_orders', sa.Column('sell_anchor', sa.String(length=24), nullable=False, server_default=''))
    op.add_column('sim_orders', sa.Column('sell_anchor_time', sa.String(length=8), nullable=True))
    op.add_column('sim_orders', sa.Column('sell_reason', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('sim_orders', sa.Column('pick_kind', sa.String(length=8), nullable=False, server_default='stock'))
    op.add_column('sim_orders', sa.Column('pick_role', sa.String(length=32), nullable=False, server_default=''))
    op.add_column('sim_orders', sa.Column('buy_anchor', sa.String(length=24), nullable=False, server_default='market'))
    op.add_column('sim_orders', sa.Column('buy_anchor_time', sa.String(length=8), nullable=True))
    op.add_column('sim_orders', sa.Column('underlying_code', sa.String(length=16), nullable=True))
    op.add_column('sim_orders', sa.Column('lot_id', sa.String(length=36), nullable=False, server_default=''))
    op.add_column('sim_orders', sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))

    # --- sim_positions: switch to lot-based PK ---
    # Add new columns first
    op.add_column('sim_positions', sa.Column('lot_id', sa.String(length=36), nullable=True))
    op.add_column('sim_positions', sa.Column('available_qty', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sim_positions', sa.Column('sell_anchor', sa.String(length=24), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('sell_anchor_date', sa.String(length=10), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('sell_anchor_time', sa.String(length=8), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('sell_reason', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('pick_role', sa.String(length=32), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('pick_kind', sa.String(length=8), nullable=False, server_default='stock'))
    op.add_column('sim_positions', sa.Column('underlying_code', sa.String(length=16), nullable=True))
    op.add_column('sim_positions', sa.Column('settlement_rule', sa.String(length=8), nullable=False, server_default='T+1'))
    op.add_column('sim_positions', sa.Column('entry_date', sa.String(length=10), nullable=False, server_default=''))
    op.add_column('sim_positions', sa.Column('pending_sell_qty', sa.Integer(), nullable=False, server_default='0'))

    # Backfill lot_id for existing rows (use generated UUIDs)
    op.execute("UPDATE sim_positions SET lot_id = gen_random_uuid()::text WHERE lot_id IS NULL OR lot_id = ''")
    op.alter_column('sim_positions', 'lot_id', existing_type=sa.String(length=36), nullable=False)

    # Switch primary key: drop old (ts_code), make lot_id PK, add index on ts_code
    op.drop_constraint('sim_positions_pkey', 'sim_positions', type_='primary')
    op.create_primary_key('sim_positions_pkey', 'sim_positions', ['lot_id'])
    op.create_index('ix_sim_positions_ts_code', 'sim_positions', ['ts_code'], unique=False)


def downgrade() -> None:
    # --- sim_positions: revert to ts_code PK ---
    op.drop_index('ix_sim_positions_ts_code', table_name='sim_positions')
    op.drop_constraint('sim_positions_pkey', 'sim_positions', type_='primary')
    # Keep only one row per ts_code (latest by entry_date)
    op.execute("""
        DELETE FROM sim_positions a
        USING sim_positions b
        WHERE a.entry_date < b.entry_date AND a.ts_code = b.ts_code
    """)
    op.create_primary_key('sim_positions_pkey', 'sim_positions', ['ts_code'])
    op.drop_column('sim_positions', 'pending_sell_qty')
    op.drop_column('sim_positions', 'entry_date')
    op.drop_column('sim_positions', 'settlement_rule')
    op.drop_column('sim_positions', 'underlying_code')
    op.drop_column('sim_positions', 'pick_kind')
    op.drop_column('sim_positions', 'pick_role')
    op.drop_column('sim_positions', 'sell_reason')
    op.drop_column('sim_positions', 'sell_anchor_time')
    op.drop_column('sim_positions', 'sell_anchor_date')
    op.drop_column('sim_positions', 'sell_anchor')
    op.drop_column('sim_positions', 'available_qty')
    op.drop_column('sim_positions', 'lot_id')

    op.drop_column('sim_orders', 'extra')
    op.drop_column('sim_orders', 'lot_id')
    op.drop_column('sim_orders', 'underlying_code')
    op.drop_column('sim_orders', 'buy_anchor_time')
    op.drop_column('sim_orders', 'buy_anchor')
    op.drop_column('sim_orders', 'pick_role')
    op.drop_column('sim_orders', 'pick_kind')
    op.drop_column('sim_orders', 'sell_reason')
    op.drop_column('sim_orders', 'sell_anchor_time')
    op.drop_column('sim_orders', 'sell_anchor')
