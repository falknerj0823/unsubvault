"""audit events
Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('audit_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('ip', sa.String()),
        sa.Column('detail', sa.Text()),
    )
    op.create_index('ix_audit_created_at', 'audit_events', ['created_at'])
    op.create_index('ix_audit_event_type', 'audit_events', ['event_type'])

def downgrade():
    op.drop_table('audit_events')
