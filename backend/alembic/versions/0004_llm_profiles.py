"""per-provider llm profiles
Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('llm_profiles',
        sa.Column('provider', sa.String(), primary_key=True),
        sa.Column('model', sa.String()),
        sa.Column('base_url', sa.String()),
        sa.Column('api_key_encrypted', sa.String()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    conn = op.get_bind()
    old = conn.execute(sa.text("select provider, model, base_url, api_key_encrypted from llm_config where id = 1")).first()
    if old:
        conn.execute(sa.text("insert into llm_profiles (provider, model, base_url, api_key_encrypted) values (:p, :m, :b, :k)"),
                     {"p": old[0], "m": old[1], "b": old[2], "k": old[3]})
        conn.execute(sa.text("insert into app_settings (key, value, encrypted) values ('llm_active_provider', :p, false) "
                             "on conflict (key) do update set value = :p"), {"p": old[0]})
    op.drop_table('llm_config')

def downgrade():
    op.create_table('llm_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String()),
        sa.Column('base_url', sa.String()),
        sa.Column('api_key_encrypted', sa.String()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    conn = op.get_bind()
    active = conn.execute(sa.text("select value from app_settings where key = 'llm_active_provider'")).scalar()
    row = conn.execute(sa.text("select provider, model, base_url, api_key_encrypted from llm_profiles where provider = :p"), {"p": active}).first() if active else None
    if row:
        conn.execute(sa.text("insert into llm_config (id, provider, model, base_url, api_key_encrypted) values (1, :p, :m, :b, :k)"),
                     {"p": row[0], "m": row[1], "b": row[2], "k": row[3]})
    op.drop_table('llm_profiles')
