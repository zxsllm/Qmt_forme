"""fixup theme hot columns: align with Tushare real fields

Revision ID: d6f8e2a3b410
Revises: c5e7d1f8a209
Create Date: 2026-05-08 21:00:00.000000

修复 c5e7d1f8a209 的字段不匹配:
  - moneyflow_cnt_ths.index_close → industry_index (Tushare 返回的实际字段名)
  - dc_index 增加 level 字段 (Tushare 返回但建表时漏了)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6f8e2a3b410'
down_revision: Union[str, Sequence[str], None] = 'c5e7d1f8a209'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('moneyflow_cnt_ths', 'index_close', new_column_name='industry_index')
    op.add_column('dc_index', sa.Column('level', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('dc_index', 'level')
    op.alter_column('moneyflow_cnt_ths', 'industry_index', new_column_name='index_close')
