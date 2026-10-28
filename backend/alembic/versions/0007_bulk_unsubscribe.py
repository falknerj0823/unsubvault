"""bulk unsubscribe
Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('email_records', sa.Column('unsubscribe_one_click', sa.Boolean(), server_default=sa.false()))
    op.add_column('email_records', sa.Column('unsubscribe_result', sa.String()))
    op.add_column('email_records', sa.Column('unsubscribe_error', sa.String()))
    op.add_column('email_records', sa.Column('unsubscribed_at', sa.DateTime()))
    op.create_table('unsub_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.Column('selection', sa.Text(), nullable=False),
        sa.Column('total', sa.Integer(), server_default='0'),
        sa.Column('done', sa.Integer(), server_default='0'),
        sa.Column('confirmed', sa.Integer(), server_default='0'),
        sa.Column('unverified', sa.Integer(), server_default='0'),
        sa.Column('manual', sa.Integer(), server_default='0'),
        sa.Column('failed', sa.Integer(), server_default='0'),
        sa.Column('simulated', sa.Integer(), server_default='0'),
        sa.Column('error', sa.String()),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime()),
    )

def downgrade():
    op.drop_table('unsub_jobs')
    for c in ('unsubscribed_at', 'unsubscribe_error', 'unsubscribe_result', 'unsubscribe_one_click'):
        op.drop_column('email_records', c)
