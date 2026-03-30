"""add news_classified and anns_classified tables

Revision ID: 3216d25c234b
Revises: 1235ebb049c3
Create Date: 2026-03-29 23:43:28.805391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3216d25c234b'
down_revision: Union[str, Sequence[str], None] = '1235ebb049c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('news_classified',
        sa.Column('news_id', sa.Integer(), nullable=False),
        sa.Column('news_scope', sa.String(length=16), nullable=False),
        sa.Column('time_slot', sa.String(length=16), nullable=False),
        sa.Column('sentiment', sa.String(length=16), nullable=False),
        sa.Column('related_codes', sa.Text(), nullable=True),
        sa.Column('related_industries', sa.Text(), nullable=True),
        sa.Column('keywords', sa.Text(), nullable=True),
        sa.Column('classified_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('news_id')
    )
    op.create_index('ix_news_classified_news_scope', 'news_classified', ['news_scope'])
    op.create_index('ix_news_classified_sentiment', 'news_classified', ['sentiment'])
    op.create_index('ix_news_classified_time_slot', 'news_classified', ['time_slot'])

    op.create_table('anns_classified',
        sa.Column('anns_id', sa.Integer(), nullable=False),
        sa.Column('ann_type', sa.String(length=32), nullable=False),
        sa.Column('sentiment', sa.String(length=16), nullable=False),
        sa.Column('keywords', sa.Text(), nullable=True),
        sa.Column('classified_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('anns_id')
    )
    op.create_index('ix_anns_classified_ann_type', 'anns_classified', ['ann_type'])
    op.create_index('ix_anns_classified_sentiment', 'anns_classified', ['sentiment'])


def downgrade() -> None:
    op.drop_index('ix_anns_classified_sentiment', table_name='anns_classified')
    op.drop_index('ix_anns_classified_ann_type', table_name='anns_classified')
    op.drop_table('anns_classified')
    op.drop_index('ix_news_classified_time_slot', table_name='news_classified')
    op.drop_index('ix_news_classified_sentiment', table_name='news_classified')
    op.drop_index('ix_news_classified_news_scope', table_name='news_classified')
    op.drop_table('news_classified')
