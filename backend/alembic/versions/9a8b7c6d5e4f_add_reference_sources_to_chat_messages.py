"""add reference_sources to chat_messages

Revision ID: 9a8b7c6d5e4f
Revises: e5f6a7b8c9d0
Create Date: 2026-08-11 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9a8b7c6d5e4f'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 知识问答引用来源（[{chunk_id, score}]，供历史消息回显时重拼完整 sources）
    op.add_column(
        'chat_messages',
        sa.Column('reference_sources', sa.JSON(), nullable=True, comment='知识问答引用来源（[{chunk_id, score}]）'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'reference_sources')
