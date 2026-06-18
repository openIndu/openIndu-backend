"""add user nickname

Revision ID: 20260618_add_user_nickname
Revises: 0cb824e923d0
Create Date: 2026-06-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20260618_add_user_nickname"
down_revision = "0cb824e923d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "nickname")
