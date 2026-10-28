"""broker status
Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('broker_status',
        sa.Column('broker_id', sa.String(), primary_key=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('requested_at', sa.DateTime()),
        sa.Column('confirmed_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('broker_status')
