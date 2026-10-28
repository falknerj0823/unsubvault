"""registry sync and link checks
Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('registry_brokers',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('website', sa.String()),
        sa.Column('email', sa.String()),
        sa.Column('optout_text', sa.Text()),
        sa.Column('date_added', sa.String()),
        sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('first_seen_sync', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('changed_sync', sa.Integer()),
        sa.Column('removed_sync', sa.Integer()),
        sa.Column('first_seen_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_seen_at', sa.DateTime()),
    )
    op.create_table('registry_syncs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('total', sa.Integer(), server_default='0'),
        sa.Column('new', sa.Integer(), server_default='0'),
        sa.Column('changed', sa.Integer(), server_default='0'),
        sa.Column('removed', sa.Integer(), server_default='0'),
        sa.Column('baseline', sa.Integer(), server_default='0'),
    )
    op.create_table('link_checks',
        sa.Column('broker_id', sa.String(), primary_key=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('http_status', sa.Integer()),
        sa.Column('final_url', sa.String()),
        sa.Column('note', sa.String()),
    )

def downgrade():
    op.drop_table('link_checks')
    op.drop_table('registry_syncs')
    op.drop_table('registry_brokers')
