"""add visitor and client identifiers for PV/UV metrics

Adds browser-scoped visitor_id to visit_events for PV/UV metrics and
client_id to login_sessions for accurate same-browser account switching. The
old IP/User-Agent fallback remains for historical rows and old clients.

Revision ID: 20260626_add_visit_client_ids
Revises: 20260626_remove_software_series
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op


revision = "20260626_add_visit_client_ids"
down_revision = "20260626_remove_software_series"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE visit_events ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(64)")
    op.execute("ALTER TABLE visit_events ADD COLUMN IF NOT EXISTS event_type VARCHAR(32) NOT NULL DEFAULT 'page_view'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_visit_events_visitor_id ON visit_events (visitor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_visit_events_event_type ON visit_events (event_type)")
    op.execute("ALTER TABLE visit_events ALTER COLUMN event_type DROP DEFAULT")

    op.execute("ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS client_id VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_sessions_client_id ON login_sessions (client_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_login_sessions_client_id")
    op.execute("ALTER TABLE login_sessions DROP COLUMN IF EXISTS client_id")

    op.execute("DROP INDEX IF EXISTS ix_visit_events_event_type")
    op.execute("DROP INDEX IF EXISTS ix_visit_events_visitor_id")
    op.execute("ALTER TABLE visit_events DROP COLUMN IF EXISTS event_type")
    op.execute("ALTER TABLE visit_events DROP COLUMN IF EXISTS visitor_id")
