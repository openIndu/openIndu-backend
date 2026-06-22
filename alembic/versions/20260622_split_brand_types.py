"""split brand type into doc_brand and sw_brand

Revision ID: 20260622_split_brand_types
Revises: 20260622_add_brand_value_to_series
Create Date: 2026-06-22 20:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "20260622_split_brand_types"
down_revision = "20260622_add_brand_value_to_series"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copy every brand entry to doc_brand and sw_brand
    op.execute(
        sa.text("""
            INSERT INTO resource_tags (type, value, label_zh, brand_value, is_active, sort_order)
            SELECT 'doc_brand', value, label_zh, brand_value, is_active, sort_order
            FROM resource_tags
            WHERE type = 'brand'
            ON CONFLICT DO NOTHING
        """)
    )
    op.execute(
        sa.text("""
            INSERT INTO resource_tags (type, value, label_zh, brand_value, is_active, sort_order)
            SELECT 'sw_brand', value, label_zh, brand_value, is_active, sort_order
            FROM resource_tags
            WHERE type = 'brand'
            ON CONFLICT DO NOTHING
        """)
    )
    # Remove old shared brand entries
    op.execute(sa.text("DELETE FROM resource_tags WHERE type = 'brand'"))


def downgrade() -> None:
    # Restore brand from doc_brand (they should be identical)
    op.execute(
        sa.text("""
            INSERT INTO resource_tags (type, value, label_zh, brand_value, is_active, sort_order)
            SELECT 'brand', value, label_zh, brand_value, is_active, sort_order
            FROM resource_tags
            WHERE type = 'doc_brand'
            ON CONFLICT DO NOTHING
        """)
    )
    op.execute(sa.text("DELETE FROM resource_tags WHERE type IN ('doc_brand', 'sw_brand')"))
