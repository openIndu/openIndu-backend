"""rename visit_events.visitor_id to client_id

Unify the browser identifier: a single client_id now serves both PV/UV
analytics (was visitor_id) and login-session scoping (already client_id).
This renames the visit_events column so the data model matches the unified
client_id concept; existing rows are preserved in place.

Revision ID: 20260626_rename_visitor_to_client
Revises: 20260626_add_visit_client_ids
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op


revision = "20260626_rename_visitor_to_client"
down_revision = "20260626_add_visit_client_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE visit_events RENAME COLUMN visitor_id TO client_id")
    op.execute("ALTER INDEX IF EXISTS ix_visit_events_visitor_id RENAME TO ix_visit_events_client_id")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_visit_events_client_id RENAME TO ix_visit_events_visitor_id")
    op.execute("ALTER TABLE visit_events RENAME COLUMN client_id TO visitor_id")
