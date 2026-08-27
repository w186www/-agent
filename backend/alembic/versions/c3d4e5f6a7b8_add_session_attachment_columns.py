"""add session attachment columns

Revision ID: c3d4e5f6a7b8
Revises: e5f6a7b8c9d0
Create Date: 2026-08-11 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = '9a8b7c6d5e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sessions', sa.Column('attachment_name', sa.String(length=255), nullable=True, comment='会话绑定附件文件名（对话附件，storage_scene=2 提取文本后绑定）'))
    op.add_column('sessions', sa.Column('attachment_text', sa.Text().with_variant(mysql.MEDIUMTEXT(), 'mysql'), nullable=True, comment='会话绑定附件提取文本'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'attachment_text')
    op.drop_column('sessions', 'attachment_name')
