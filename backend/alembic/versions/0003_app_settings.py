"""app settings
Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('app_settings',
        sa.Column('key', sa.String(), primary_key=True),
        sa.Column('value', sa.String()),
        sa.Column('encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

def downgrade():
    op.drop_table('app_settings')
