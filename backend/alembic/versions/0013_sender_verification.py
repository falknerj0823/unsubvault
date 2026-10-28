"""sender verification
Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('email_records', sa.Column('verify_verdict', sa.String()))
    op.add_column('email_records', sa.Column('verify_summary', sa.String()))
    op.create_table('sender_checks',
        sa.Column('domain', sa.String(), primary_key=True),
        sa.Column('checked_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('facts', sa.Text(), nullable=False),
    )

def downgrade():
    op.drop_table('sender_checks')
    op.drop_column('email_records', 'verify_summary')
    op.drop_column('email_records', 'verify_verdict')
