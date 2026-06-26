"""remove software series legacy fields

Software no longer has a product-series concept. Document resources keep
``documents.series`` and ``doc_series`` tags, but software is categorized by
brand/category plus version rows only. This migration drops the legacy
``software.series`` column/index and removes any historical ``sw_series`` tags.

Revision ID: 20260626_remove_software_series
Revises: 20260625_add_user_deleted_at
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op


revision = "20260626_remove_software_series"
down_revision = "20260625_add_user_deleted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_software_series")
    op.execute("ALTER TABLE software DROP COLUMN IF EXISTS series")
    op.execute("DELETE FROM resource_tags WHERE type = 'sw_series'")


def downgrade() -> None:
    op.execute("ALTER TABLE software ADD COLUMN IF NOT EXISTS series VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_software_series ON software (series)")
    # Historical sw_series seed data is intentionally not re-created. The current
    # application no longer exposes software-series management, and recreating
    # obsolete tags during downgrade would make the data model inconsistent.
