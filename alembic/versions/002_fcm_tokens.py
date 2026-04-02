"""create fcm_tokens table

Revision ID: 002_fcm_tokens
Revises: 001_user_prefs
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "002_fcm_tokens"
down_revision = "001_user_prefs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fcm_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_fcm_tokens_token", "fcm_tokens", ["token"])


def downgrade():
    op.drop_index("ix_fcm_tokens_token", "fcm_tokens")
    op.drop_table("fcm_tokens")
