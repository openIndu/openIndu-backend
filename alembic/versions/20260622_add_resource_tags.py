"""add resource_tags table with seed data

Revision ID: 20260622_add_resource_tags
Revises: 20260621_add_software_is_published
Create Date: 2026-06-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260622_add_resource_tags"
down_revision = "20260621_add_software_is_published"
branch_labels = None
depends_on = None

_SEED = [
    # brands (shared)
    ("brand", "siemens", "西门子", 1),
    ("brand", "mitsubishi", "三菱", 2),
    ("brand", "omron", "欧姆龙", 3),
    ("brand", "keyence", "基恩士", 4),
    ("brand", "inovance", "汇川", 5),
    # document categories
    ("doc_category", "plc-manual", "PLC 编程手册", 1),
    ("doc_category", "hardware-manual", "硬件手册", 2),
    ("doc_category", "driver-manual", "驱动器手册", 3),
    ("doc_category", "hmi-manual", "HMI 手册", 4),
    ("doc_category", "software-manual", "软件手册", 5),
    ("doc_category", "best-practice", "最佳实践", 6),
    ("doc_category", "electrical-standard", "电气规范", 7),
    ("doc_category", "other", "其他", 8),
    # software categories
    ("sw_category", "plc-ide", "PLC 编程软件", 1),
    ("sw_category", "hmi-ide", "HMI 编程软件", 2),
    ("sw_category", "plc-driver", "驱动软件", 3),
    ("sw_category", "utility", "调试工具", 4),
    ("sw_category", "firmware", "固件升级", 5),
    ("sw_category", "other", "其他", 6),
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS resource_tags (
            id BIGSERIAL NOT NULL,
            type VARCHAR(20) NOT NULL,
            value VARCHAR(100) NOT NULL,
            label_zh VARCHAR(200) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_resource_tags_type ON resource_tags (type)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_resource_tags_type_value ON resource_tags (type, value)")

    for tag_type, value, label_zh, sort_order in _SEED:
        op.execute(
            sa.text(
                "INSERT INTO resource_tags (type, value, label_zh, is_active, sort_order) "
                "VALUES (:t, :v, :l, true, :s) ON CONFLICT (type, value) DO NOTHING"
            ).bindparams(t=tag_type, v=value, l=label_zh, s=sort_order)
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resource_tags_type_value")
    op.execute("DROP INDEX IF EXISTS ix_resource_tags_type")
    op.drop_table("resource_tags")
