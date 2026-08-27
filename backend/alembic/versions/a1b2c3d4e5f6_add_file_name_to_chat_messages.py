"""add file_name to chat_messages

Revision ID: a1b2c3d4e5f6
Revises: 64ff9c9de6ba
Create Date: 2026-08-10 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '774abeb26107'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 会话附件在 chat_messages 上回显文件名（供前端展示 📎 附件标识）
    op.add_column('chat_messages', sa.Column('file_name', sa.String(length=255), nullable=True, comment='附件原始文件名'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'file_name')
