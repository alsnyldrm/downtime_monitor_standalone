"""add user theme and sidebar_pinned

Revision ID: 001_user_prefs
Revises: 
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa

revision = '001_user_prefs'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('theme', sa.String(10), nullable=False, server_default='dark'))
    op.add_column('users', sa.Column('sidebar_pinned', sa.Boolean(), nullable=False, server_default='1'))


def downgrade():
    op.drop_column('users', 'sidebar_pinned')
    op.drop_column('users', 'theme')
