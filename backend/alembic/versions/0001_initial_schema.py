"""initial schema
Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('provider_type', sa.Enum('microsoft','google','imap', name='providertype'), nullable=False),
        sa.Column('email_address', sa.String()),
        sa.Column('access_token', sa.String()),
        sa.Column('refresh_token', sa.String()),
        sa.Column('token_expires_at', sa.DateTime()),
        sa.Column('imap_host', sa.String()),
        sa.Column('imap_port', sa.Integer()),
        sa.Column('imap_username', sa.String()),
        sa.Column('imap_password_encrypted', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_table('scan_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Enum('pending','running','complete','failed', name='scanstatus'), nullable=False),
        sa.Column('folder', sa.String()),
        sa.Column('dry_run', sa.Boolean()),
        sa.Column('emails_scanned', sa.Integer(), server_default='0'),
        sa.Column('emails_unsubscribed', sa.Integer(), server_default='0'),
        sa.Column('emails_failed', sa.Integer(), server_default='0'),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime()),
    )
    op.create_table('email_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scan_run_id', sa.Integer(), sa.ForeignKey('scan_runs.id', ondelete='SET NULL')),
        sa.Column('message_id', sa.String()),
        sa.Column('subject', sa.String()),
        sa.Column('sender_name', sa.String()),
        sa.Column('sender_email', sa.String()),
        sa.Column('received_at', sa.DateTime()),
        sa.Column('is_newsletter', sa.Boolean()),
        sa.Column('is_promotional', sa.Boolean()),
        sa.Column('confidence', sa.Float()),
        sa.Column('category', sa.String()),
        sa.Column('classification_reason', sa.String()),
        sa.Column('action', sa.Enum('none','unsubscribed','unsubscribe_pending','unsubscribe_failed','archived','deleted','labeled', name='emailaction')),
        sa.Column('unsubscribe_url', sa.String()),
        sa.Column('unsubscribe_method', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.UniqueConstraint('account_id', 'message_id', name='uq_account_message'),
    )

def downgrade():
    op.drop_table('email_records')
    op.drop_table('scan_runs')
    op.drop_table('accounts')
    op.execute('DROP TYPE IF EXISTS emailaction')
    op.execute('DROP TYPE IF EXISTS scanstatus')
    op.execute('DROP TYPE IF EXISTS providertype')
