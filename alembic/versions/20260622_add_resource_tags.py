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
    op.create_table(
        "resource_tags",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.Column("label_zh", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resource_tags_type", "resource_tags", ["type"])
    op.create_index("ix_resource_tags_type_value", "resource_tags", ["type", "value"], unique=True)

    resource_tags = sa.table(
        "resource_tags",
        sa.column("type", sa.String),
        sa.column("value", sa.String),
        sa.column("label_zh", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(resource_tags, [
        {"type": t, "value": v, "label_zh": l, "sort_order": s}
        for t, v, l, s in _SEED
    ])


def downgrade() -> None:
    op.drop_index("ix_resource_tags_type_value", table_name="resource_tags")
    op.drop_index("ix_resource_tags_type", table_name="resource_tags")
    op.drop_table("resource_tags")
