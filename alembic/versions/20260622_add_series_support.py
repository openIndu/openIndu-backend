"""add series support: parent_value to resource_tags, series to documents/software

Revision ID: 20260622_add_series_support
Revises: 20260622_add_resource_tags
Create Date: 2026-06-22 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "20260622_add_series_support"
down_revision = "20260622_add_resource_tags"
branch_labels = None
depends_on = None

_DOC_SERIES = [
    # PLC series (parent: plc-manual)
    ("doc_series", "fx", "FX系列", "plc-manual", 1),
    ("doc_series", "q", "Q系列", "plc-manual", 2),
    ("doc_series", "iQ-R", "iQ-R系列", "plc-manual", 3),
    ("doc_series", "s7-1200", "S7-1200", "plc-manual", 4),
    ("doc_series", "s7-300", "S7-300/400", "plc-manual", 5),
    ("doc_series", "cp1e", "CP1E系列", "plc-manual", 6),
    ("doc_series", "cp1h", "CP1H系列", "plc-manual", 7),
    ("doc_series", "slc500", "SLC 500", "plc-manual", 8),
    # Driver/servo series (parent: driver-manual)
    ("doc_series", "melservo-j5", "MELSERVO-J5", "driver-manual", 1),
    ("doc_series", "melservo-j4", "MELSERVO-J4", "driver-manual", 2),
    ("doc_series", "sinamics-s120", "SINAMICS S120", "driver-manual", 3),
    ("doc_series", "sinamics-g120", "SINAMICS G120", "driver-manual", 4),
    ("doc_series", "g5-series", "G5系列", "driver-manual", 5),
    # HMI series (parent: hmi-manual)
    ("doc_series", "got2000", "GOT2000系列", "hmi-manual", 1),
    ("doc_series", "got1000", "GOT1000系列", "hmi-manual", 2),
    ("doc_series", "simatic-tp", "SIMATIC TP", "hmi-manual", 3),
    ("doc_series", "simatic-ktp", "SIMATIC KTP", "hmi-manual", 4),
    ("doc_series", "ns-series", "NS系列", "hmi-manual", 5),
    # Hardware series (parent: hardware-manual)
    ("doc_series", "fx5u", "FX5U", "hardware-manual", 1),
    ("doc_series", "iQ-R-hw", "iQ-R硬件", "hardware-manual", 2),
    ("doc_series", "et200", "ET 200系列", "hardware-manual", 3),
]

_SW_SERIES = [
    # PLC IDE series (parent: plc-ide)
    ("sw_series", "gxworks3", "GX Works3", "plc-ide", 1),
    ("sw_series", "gxworks2", "GX Works2", "plc-ide", 2),
    ("sw_series", "tia-portal", "TIA Portal", "plc-ide", 3),
    ("sw_series", "cx-programmer", "CX-Programmer", "plc-ide", 4),
    # HMI IDE series (parent: hmi-ide)
    ("sw_series", "gt-designer3", "GT Designer3", "hmi-ide", 1),
    ("sw_series", "wincc", "WinCC", "hmi-ide", 2),
    ("sw_series", "cx-designer", "CX-Designer", "hmi-ide", 3),
    # Driver software series (parent: plc-driver)
    ("sw_series", "melsoft-mr", "MR Configurator2", "plc-driver", 1),
    ("sw_series", "starter", "STARTER", "plc-driver", 2),
]


def upgrade() -> None:
    # Add parent_value column to resource_tags
    op.execute("ALTER TABLE resource_tags ADD COLUMN IF NOT EXISTS parent_value VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_resource_tags_parent_value ON resource_tags (parent_value)")

    # Add series column to documents
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS series VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_series ON documents (series)")

    # Add series column to software
    op.execute("ALTER TABLE software ADD COLUMN IF NOT EXISTS series VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_software_series ON software (series)")

    # Seed doc series
    for tag_type, value, label_zh, parent_value, sort_order in _DOC_SERIES:
        op.execute(
            sa.text(
                "INSERT INTO resource_tags (type, value, label_zh, parent_value, is_active, sort_order) "
                "VALUES (:t, :v, :l, :p, true, :s) ON CONFLICT DO NOTHING"
            ).bindparams(t=tag_type, v=value, l=label_zh, p=parent_value, s=sort_order)
        )

    # Seed sw series
    for tag_type, value, label_zh, parent_value, sort_order in _SW_SERIES:
        op.execute(
            sa.text(
                "INSERT INTO resource_tags (type, value, label_zh, parent_value, is_active, sort_order) "
                "VALUES (:t, :v, :l, :p, true, :s) ON CONFLICT DO NOTHING"
            ).bindparams(t=tag_type, v=value, l=label_zh, p=parent_value, s=sort_order)
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_software_series")
    op.execute("DROP INDEX IF EXISTS ix_documents_series")
    op.execute("DROP INDEX IF EXISTS ix_resource_tags_parent_value")
    op.execute("ALTER TABLE software DROP COLUMN IF EXISTS series")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS series")
    op.execute("DELETE FROM resource_tags WHERE type IN ('doc_series', 'sw_series')")
    op.execute("ALTER TABLE resource_tags DROP COLUMN IF EXISTS parent_value")
