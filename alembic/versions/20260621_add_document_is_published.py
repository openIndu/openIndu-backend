"""add document is_published

Revision ID: 20260621_add_document_is_published
Revises: 20260618_add_user_nickname
Create Date: 2026-06-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260621_add_document_is_published"
down_revision = "20260618_add_user_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("documents", "is_published")
