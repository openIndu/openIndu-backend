"""add feedback column to chat_messages

Revision ID: 20260630_add_message_feedback
Revises: 20260630_add_brand_mappings
Create Date: 2026-06-30
"""
from alembic import op

revision = "20260630_add_message_feedback"
down_revision = "20260630_add_brand_mappings"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS feedback SMALLINT DEFAULT NULL"
    )


def downgrade():
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS feedback")
