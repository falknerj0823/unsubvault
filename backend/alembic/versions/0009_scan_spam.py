"""scan spam counter
Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('scan_runs', sa.Column('emails_spam', sa.Integer(), server_default='0'))

def downgrade():
    op.drop_column('scan_runs', 'emails_spam')
