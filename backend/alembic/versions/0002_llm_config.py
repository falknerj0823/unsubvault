"""llm config
Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('llm_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String()),
        sa.Column('base_url', sa.String()),
        sa.Column('api_key_encrypted', sa.String()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('llm_config')
