"""add brand_value to resource_tags for series brand linkage

Revision ID: 20260622_add_brand_value_to_series
Revises: 20260622_add_series_support
Create Date: 2026-06-22 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "20260622_add_brand_value_to_series"
down_revision = "20260622_add_series_support"
branch_labels = None
depends_on = None

# (value, brand_value) — only entries where brand_value is non-null
_BRAND_MAP = [
    # doc_series PLC
    ("fx", "mitsubishi"),
    ("q", "mitsubishi"),
    ("iQ-R", "mitsubishi"),
    ("s7-1200", "siemens"),
    ("s7-300", "siemens"),
    ("cp1e", "omron"),
    ("cp1h", "omron"),
    # doc_series driver/servo
    ("melservo-j5", "mitsubishi"),
    ("melservo-j4", "mitsubishi"),
    ("sinamics-s120", "siemens"),
    ("sinamics-g120", "siemens"),
    ("g5-series", "keyence"),
    # doc_series HMI
    ("got2000", "mitsubishi"),
    ("got1000", "mitsubishi"),
    ("simatic-tp", "siemens"),
    ("simatic-ktp", "siemens"),
    ("ns-series", "omron"),
    # doc_series hardware
    ("fx5u", "mitsubishi"),
    ("iQ-R-hw", "mitsubishi"),
    ("et200", "siemens"),
    # sw_series PLC IDE
    ("gxworks3", "mitsubishi"),
    ("gxworks2", "mitsubishi"),
    ("tia-portal", "siemens"),
    ("cx-programmer", "omron"),
    # sw_series HMI IDE
    ("gt-designer3", "mitsubishi"),
    ("wincc", "siemens"),
    ("cx-designer", "omron"),
    # sw_series driver software
    ("melsoft-mr", "mitsubishi"),
    ("starter", "siemens"),
]


def upgrade() -> None:
    op.execute("ALTER TABLE resource_tags ADD COLUMN IF NOT EXISTS brand_value VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_resource_tags_brand_value ON resource_tags (brand_value)")

    for value, brand in _BRAND_MAP:
        op.execute(
            sa.text(
                "UPDATE resource_tags SET brand_value = :b "
                "WHERE value = :v AND type IN ('doc_series', 'sw_series')"
            ).bindparams(b=brand, v=value)
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resource_tags_brand_value")
    op.execute("ALTER TABLE resource_tags DROP COLUMN IF EXISTS brand_value")
