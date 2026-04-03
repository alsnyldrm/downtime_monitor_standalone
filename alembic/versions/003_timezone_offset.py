"""add timezone_offset to users

Revision ID: 003_timezone_offset
Revises: 002_fcm_tokens
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = "003_timezone_offset"
down_revision = "002_fcm_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("timezone_offset", sa.Float(), nullable=False, server_default="3"),
    )


def downgrade():
    op.drop_column("users", "timezone_offset")
