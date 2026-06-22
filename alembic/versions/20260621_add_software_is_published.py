"""add software is_published

Revision ID: 20260621_add_software_is_published
Revises: 20260621_add_document_is_published
Create Date: 2026-06-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260621_add_software_is_published"
down_revision = "20260621_add_document_is_published"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE software ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.drop_column("software", "is_published")
