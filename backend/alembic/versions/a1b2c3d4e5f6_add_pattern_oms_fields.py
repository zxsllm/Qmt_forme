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
    # 幂等：用 ADD COLUMN IF NOT EXISTS 处理 schema drift（available_qty 等列可能已存在）
    sim_orders_cols = [
        ("sell_anchor",        "VARCHAR(24)  NOT NULL DEFAULT ''"),
        ("sell_anchor_time",   "VARCHAR(8)"),
        ("sell_reason",        "VARCHAR(64)  NOT NULL DEFAULT ''"),
        ("pick_kind",          "VARCHAR(8)   NOT NULL DEFAULT 'stock'"),
        ("pick_role",          "VARCHAR(32)  NOT NULL DEFAULT ''"),
        ("buy_anchor",         "VARCHAR(24)  NOT NULL DEFAULT 'market'"),
        ("buy_anchor_time",    "VARCHAR(8)"),
        ("underlying_code",    "VARCHAR(16)"),
        ("lot_id",             "VARCHAR(36)  NOT NULL DEFAULT ''"),
        ("extra",              "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ]
    for col, decl in sim_orders_cols:
        op.execute(f"ALTER TABLE sim_orders ADD COLUMN IF NOT EXISTS {col} {decl}")

    sim_positions_cols = [
        ("lot_id",             "VARCHAR(36)"),
        ("available_qty",      "INTEGER NOT NULL DEFAULT 0"),
        ("sell_anchor",        "VARCHAR(24)  NOT NULL DEFAULT ''"),
        ("sell_anchor_date",   "VARCHAR(10)  NOT NULL DEFAULT ''"),
        ("sell_anchor_time",   "VARCHAR(8)   NOT NULL DEFAULT ''"),
        ("sell_reason",        "VARCHAR(64)  NOT NULL DEFAULT ''"),
        ("pick_role",          "VARCHAR(32)  NOT NULL DEFAULT ''"),
        ("pick_kind",          "VARCHAR(8)   NOT NULL DEFAULT 'stock'"),
        ("underlying_code",    "VARCHAR(16)"),
        ("settlement_rule",    "VARCHAR(8)   NOT NULL DEFAULT 'T+1'"),
        ("entry_date",         "VARCHAR(10)  NOT NULL DEFAULT ''"),
        ("pending_sell_qty",   "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, decl in sim_positions_cols:
        op.execute(f"ALTER TABLE sim_positions ADD COLUMN IF NOT EXISTS {col} {decl}")

    # Backfill lot_id（仅对未填的）
    op.execute(
        "UPDATE sim_positions SET lot_id = gen_random_uuid()::text "
        "WHERE lot_id IS NULL OR lot_id = ''"
    )
    op.execute("ALTER TABLE sim_positions ALTER COLUMN lot_id SET NOT NULL")

    # 幂等切 PK：先看现在 PK 是不是 ts_code
    op.execute("""
        DO $$
        DECLARE
            pk_cols TEXT;
        BEGIN
            SELECT string_agg(a.attname, ',') INTO pk_cols
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'sim_positions'::regclass AND i.indisprimary;

            IF pk_cols <> 'lot_id' THEN
                ALTER TABLE sim_positions DROP CONSTRAINT sim_positions_pkey;
                ALTER TABLE sim_positions ADD PRIMARY KEY (lot_id);
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sim_positions_ts_code ON sim_positions (ts_code)")


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
