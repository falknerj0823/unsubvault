"""sender rules
Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('email_records', sa.Column('prior_category', sa.String()))
    op.add_column('email_records', sa.Column('prior_action', sa.String()))
    op.create_table('sender_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_email', sa.String(), nullable=False),
        sa.Column('decision', sa.String(), nullable=False),
        sa.Column('sender_name', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('account_id', 'sender_email', name='uq_rule_account_sender'),
    )

def downgrade():
    op.drop_table('sender_rules')
    op.drop_column('email_records', 'prior_action')
    op.drop_column('email_records', 'prior_category')
