"""add users.deleted_at for soft-delete

Adds a nullable ``deleted_at`` datetime column to ``users``. NULL = live user;
set = removed from the admin UI and from login. Associated rows in
``visit_events`` / ``download_records`` / ``login_sessions`` /
``admin_audit_log`` are preserved for audit history.

Revision ID: 20260625_add_user_deleted_at
Revises: 20260623_version_name_and_publish
Create Date: 2026-06-25 00:00:00.000000
"""
from alembic import op


revision = "20260625_add_user_deleted_at"
down_revision = "20260623_version_name_and_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE")
    # Partial index on deleted_at IS NULL so the list_users query
    # (...WHERE deleted_at IS NULL ORDER BY created_at DESC) stays fast as the
    # table grows. We do NOT want this index to cover the (rare) soft-deleted
    # rows — those are only inspected by audit queries.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_deleted_at_null "
        "ON users (created_at DESC) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_deleted_at_null")
    op.drop_column("users", "deleted_at")
