"""add chat_logs for smart consultation (RAG chat)

Creates chat_logs: per-question audit + daily-quota counter for the
member-facing RAG consultation endpoint (/api/v1/chat). Daily limit is
COUNT(*) WHERE user_id=? AND created_at::date = today (admin exempt).

Revision ID: 20260628_add_chat_logs
Revises: 20260626_rename_visitor_to_client
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op


revision = "20260628_add_chat_logs"
down_revision = "20260626_rename_visitor_to_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            ip_address VARCHAR(64),
            question TEXT,
            source_docs TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_logs_user_id ON chat_logs (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_logs_created_at ON chat_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_logs_created_at")
    op.execute("DROP INDEX IF EXISTS ix_chat_logs_user_id")
    op.execute("DROP TABLE IF EXISTS chat_logs")
