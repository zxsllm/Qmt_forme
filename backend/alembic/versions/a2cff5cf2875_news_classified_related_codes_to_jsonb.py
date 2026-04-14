"""news_classified related_codes to jsonb

Revision ID: a2cff5cf2875
Revises: 9dd4ee2ba5bd
Create Date: 2026-04-14 21:32:49.695756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a2cff5cf2875'
down_revision: Union[str, Sequence[str], None] = '9dd4ee2ba5bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert related_codes/related_industries/keywords from Text to JSONB."""
    for col in ("related_codes", "related_industries", "keywords"):
        op.execute(
            f'ALTER TABLE news_classified '
            f'ALTER COLUMN "{col}" TYPE jsonb USING "{col}"::jsonb'
        )
    # GIN index for related_codes containment queries
    op.create_index(
        "ix_news_classified_related_codes_gin",
        "news_classified",
        ["related_codes"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Revert JSONB columns back to Text."""
    op.drop_index("ix_news_classified_related_codes_gin", table_name="news_classified")
    for col in ("related_codes", "related_industries", "keywords"):
        op.execute(
            f'ALTER TABLE news_classified '
            f'ALTER COLUMN "{col}" TYPE text USING "{col}"::text'
        )
