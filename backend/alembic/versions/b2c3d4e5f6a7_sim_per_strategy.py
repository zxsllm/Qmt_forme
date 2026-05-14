"""add strategy_name to sim_* tables (per-strategy isolation)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15 02:00:00.000000

每个策略独立账户：sim_orders / sim_positions / sim_trades 加 strategy_name 列
+ index；sim_account 改 PK 从 id → strategy_name（一策略一行）。

Default 策略名 'default' — 兼容 manual order / 老逻辑。
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- sim_orders ---
    op.execute("ALTER TABLE sim_orders ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(32) NOT NULL DEFAULT 'default'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sim_orders_strategy_name ON sim_orders (strategy_name)")

    # --- sim_positions ---
    op.execute("ALTER TABLE sim_positions ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(32) NOT NULL DEFAULT 'default'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sim_positions_strategy_name ON sim_positions (strategy_name)")

    # --- sim_trades ---
    op.execute("ALTER TABLE sim_trades ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(32) NOT NULL DEFAULT 'default'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sim_trades_strategy_name ON sim_trades (strategy_name)")

    # --- sim_account: PK 从 id → strategy_name ---
    op.execute("ALTER TABLE sim_account ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(32) NOT NULL DEFAULT 'default'")
    op.execute("""
        DO $$
        DECLARE
            pk_cols TEXT;
        BEGIN
            SELECT string_agg(a.attname, ',') INTO pk_cols
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'sim_account'::regclass AND i.indisprimary;

            IF pk_cols <> 'strategy_name' THEN
                ALTER TABLE sim_account DROP CONSTRAINT IF EXISTS sim_account_pkey;
                -- 若有遗留 id 列，删除（保留 strategy_name 一列做 PK）
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='sim_account' AND column_name='id'
                ) THEN
                    ALTER TABLE sim_account DROP COLUMN id;
                END IF;
                ALTER TABLE sim_account ADD PRIMARY KEY (strategy_name);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sim_account DROP CONSTRAINT IF EXISTS sim_account_pkey")
    op.execute("ALTER TABLE sim_account ADD COLUMN IF NOT EXISTS id SERIAL")
    op.execute("ALTER TABLE sim_account ADD PRIMARY KEY (id)")
    op.execute("ALTER TABLE sim_account DROP COLUMN IF EXISTS strategy_name")

    op.execute("DROP INDEX IF EXISTS ix_sim_trades_strategy_name")
    op.execute("ALTER TABLE sim_trades DROP COLUMN IF EXISTS strategy_name")
    op.execute("DROP INDEX IF EXISTS ix_sim_positions_strategy_name")
    op.execute("ALTER TABLE sim_positions DROP COLUMN IF EXISTS strategy_name")
    op.execute("DROP INDEX IF EXISTS ix_sim_orders_strategy_name")
    op.execute("ALTER TABLE sim_orders DROP COLUMN IF EXISTS strategy_name")
