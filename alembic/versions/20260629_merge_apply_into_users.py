"""merge member_applications into users table

Revision ID: 20260629_merge_apply_into_users
Revises: 20260629_add_member_applications
Create Date: 2026-06-29 00:00:00.000000
"""
from alembic import op


revision = "20260629_merge_apply_into_users"
down_revision = "20260629_add_member_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS member_apply_status VARCHAR(20),
        ADD COLUMN IF NOT EXISTS member_apply_note VARCHAR(500),
        ADD COLUMN IF NOT EXISTS member_apply_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS member_reviewed_by BIGINT REFERENCES users(id)
    """)
    # Migrate latest record per user from member_applications
    op.execute("""
        UPDATE users u
        SET
            member_apply_status = ma.status,
            member_apply_note   = ma.note,
            member_apply_at     = ma.created_at,
            member_reviewed_by  = ma.reviewed_by
        FROM (
            SELECT DISTINCT ON (user_id)
                user_id, status, note, created_at, reviewed_by
            FROM member_applications
            ORDER BY user_id, created_at DESC
        ) ma
        WHERE u.id = ma.user_id
    """)
    op.execute("DROP INDEX IF EXISTS uq_member_applications_pending")
    op.execute("DROP INDEX IF EXISTS ix_member_applications_status")
    op.execute("DROP INDEX IF EXISTS ix_member_applications_user_id")
    op.execute("DROP TABLE IF EXISTS member_applications")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS member_applications (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            note VARCHAR(500),
            reviewed_by BIGINT REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP
        )
    """)
    op.execute("""
        INSERT INTO member_applications (user_id, status, note, reviewed_by, created_at)
        SELECT id, member_apply_status, member_apply_note, member_reviewed_by, member_apply_at
        FROM users
        WHERE member_apply_status IS NOT NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_member_applications_user_id ON member_applications (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_member_applications_status ON member_applications (status)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_member_applications_pending "
        "ON member_applications (user_id) WHERE status = 'pending'"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS member_apply_status")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS member_apply_note")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS member_apply_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS member_reviewed_by")
