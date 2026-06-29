"""add chat_sessions and chat_messages tables

Revision ID: 20260629_add_chat_sessions
Revises: 20260629_merge_apply_into_users
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "20260629_add_chat_sessions"
down_revision = "20260629_merge_apply_into_users"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id          BIGSERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       VARCHAR(100) NOT NULL DEFAULT '新会话',
            created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id ON chat_sessions(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id          BIGSERIAL PRIMARY KEY,
            session_id  BIGINT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role        VARCHAR(20) NOT NULL,
            content     TEXT NOT NULL DEFAULT '',
            sources     TEXT,
            mode        VARCHAR(20),
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages(session_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
