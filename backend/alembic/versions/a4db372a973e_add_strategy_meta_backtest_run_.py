"""add strategy_meta backtest_run promotion_history

Revision ID: a4db372a973e
Revises: 90405251fa2e
Create Date: 2026-03-22 19:49:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4db372a973e'
down_revision: Union[str, Sequence[str], None] = '90405251fa2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('backtest_run',
        sa.Column('run_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('strategy_name', sa.String(length=64), nullable=False),
        sa.Column('config_json', sa.Text(), nullable=False),
        sa.Column('stats_json', sa.Text(), nullable=False),
        sa.Column('equity_json', sa.Text(), nullable=False),
        sa.Column('trades_json', sa.Text(), nullable=False),
        sa.Column('filtered_json', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('run_id')
    )
    op.create_index('ix_backtest_run_strategy_name', 'backtest_run', ['strategy_name'])

    op.create_table('promotion_history',
        sa.Column('record_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('strategy_name', sa.String(length=64), nullable=False),
        sa.Column('from_level', sa.Integer(), nullable=False),
        sa.Column('to_level', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('backtest_run_id', sa.UUID(as_uuid=False), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('record_id')
    )
    op.create_index('ix_promotion_history_strategy_name', 'promotion_history', ['strategy_name'])

    op.create_table('strategy_meta',
        sa.Column('strategy_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('default_params', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('promotion_level', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('strategy_id'),
        sa.UniqueConstraint('name')
    )


def downgrade() -> None:
    op.drop_table('strategy_meta')
    op.drop_index('ix_promotion_history_strategy_name', 'promotion_history')
    op.drop_table('promotion_history')
    op.drop_index('ix_backtest_run_strategy_name', 'backtest_run')
    op.drop_table('backtest_run')
