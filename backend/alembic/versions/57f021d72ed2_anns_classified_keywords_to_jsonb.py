"""anns_classified keywords to jsonb

Revision ID: 57f021d72ed2
Revises: a2cff5cf2875
Create Date: 2026-04-14 21:58:46.547725

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57f021d72ed2'
down_revision: Union[str, Sequence[str], None] = 'a2cff5cf2875'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert anns_classified.keywords from Text to JSONB."""
    op.execute(
        'ALTER TABLE anns_classified '
        'ALTER COLUMN "keywords" TYPE jsonb USING "keywords"::jsonb'
    )


def downgrade() -> None:
    """Revert to Text."""
    op.execute(
        'ALTER TABLE anns_classified '
        'ALTER COLUMN "keywords" TYPE text USING "keywords"::text'
    )
