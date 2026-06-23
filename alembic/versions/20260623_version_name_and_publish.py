"""add per-version original_name, is_published, and version-level publish for software_versions

Adds:
- software_versions.original_name (the user-facing file name for this specific version)
- software_versions.is_published (publish per version, not per software)
- Backfill original_name from the parent Software row when the column is created

Revision ID: 20260623_version_name_and_publish
Revises: 20260622_split_brand_types
Create Date: 2026-06-23 00:00:00.000000
"""
from alembic import op


revision = "20260623_version_name_and_publish"
down_revision = "20260622_split_brand_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE software_versions ADD COLUMN IF NOT EXISTS original_name VARCHAR(500)")
    op.execute("ALTER TABLE software_versions ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT false")
    # Backfill original_name from the parent Software row so existing versions
    # have a sensible display name; admin can edit per-version names afterwards.
    op.execute("""
        UPDATE software_versions sv
        SET original_name = s.original_name
        FROM software s
        WHERE sv.software_id = s.id AND sv.original_name IS NULL
    """)
    # Mirror the existing software-level publish state onto every version so
    # nothing silently disappears from portal lists right after the migration.
    op.execute("""
        UPDATE software_versions sv
        SET is_published = s.is_published
        FROM software s
        WHERE sv.software_id = s.id
    """)


def downgrade() -> None:
    op.drop_column("software_versions", "is_published")
    op.drop_column("software_versions", "original_name")
