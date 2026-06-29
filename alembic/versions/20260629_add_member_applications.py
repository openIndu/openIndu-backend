"""add member_applications table

Revision ID: 20260629_add_member_applications
Revises: 20260628_add_chat_logs
Create Date: 2026-06-29 00:00:00.000000
"""
from alembic import op


revision = "20260629_add_member_applications"
down_revision = "20260628_add_chat_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS member_applications (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            note VARCHAR(500),
            reviewed_by BIGINT REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_member_applications_user_id ON member_applications (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_member_applications_status ON member_applications (status)")
    # 同一用户只能有一条 pending 申请
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_member_applications_pending "
        "ON member_applications (user_id) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_member_applications_pending")
    op.execute("DROP INDEX IF EXISTS ix_member_applications_status")
    op.execute("DROP INDEX IF EXISTS ix_member_applications_user_id")
    op.execute("DROP TABLE IF EXISTS member_applications")
