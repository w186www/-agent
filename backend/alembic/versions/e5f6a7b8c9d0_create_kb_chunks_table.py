"""create kb_chunks table

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('kb_chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键'),
    sa.Column('doc_id', sa.Integer(), nullable=False, comment='所属文档'),
    sa.Column('vector_id', sa.String(length=64), nullable=False, comment='Qdrant Point id（{doc_id}-{chunk_index}，与向量关联）'),
    sa.Column('chunk_index', sa.Integer(), nullable=False, comment='块序号'),
    sa.Column('content', sa.Text().with_variant(mysql.MEDIUMTEXT(), 'mysql'), nullable=False, comment='切片原文'),
    sa.Column('char_count', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='字符数'),
    sa.Column('created_at', sa.BigInteger(), server_default=sa.text('(unix_timestamp())'), nullable=False, comment='创建时间（Unix 秒）'),
    sa.ForeignKeyConstraint(['doc_id'], ['kb_documents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kb_chunks_doc_id'), 'kb_chunks', ['doc_id'], unique=False)
    op.create_index('ix_kb_chunks_doc_index', 'kb_chunks', ['doc_id', 'chunk_index'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_kb_chunks_doc_index', table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_doc_id'), table_name='kb_chunks')
    op.drop_table('kb_chunks')
