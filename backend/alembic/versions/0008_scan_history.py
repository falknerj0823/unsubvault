"""scan history detail
Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('scan_runs', sa.Column('batch_size', sa.Integer()))
    for c in ('emails_found', 'emails_known', 'emails_no_link'):
        op.add_column('scan_runs', sa.Column(c, sa.Integer(), server_default='0'))

def downgrade():
    for c in ('emails_no_link', 'emails_known', 'emails_found', 'batch_size'):
        op.drop_column('scan_runs', c)
