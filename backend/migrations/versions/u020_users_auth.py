"""Local accounts: users, external identities, personal API keys, rule ownership."""
import sqlalchemy as sa
from alembic import op

revision = 'u020_users_auth'
down_revision = 't019_rule_started_at'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.String(64), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('display_name', sa.String(80), nullable=False, server_default=''),
        sa.Column('role', sa.String(16), nullable=False, server_default='member'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.Float(), nullable=False),
    )
    op.create_table(
        'user_identities',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('open_id', sa.String(128), nullable=False),
        sa.Column('union_id', sa.String(128), nullable=True),
        sa.Column('bound_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('provider', 'open_id', name='uq_identity_provider_open'),
    )
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('name', sa.String(80), nullable=False, server_default=''),
        sa.Column('prefix', sa.String(12), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('last_used_at', sa.Float(), nullable=True),
    )
    op.add_column('monitor_rules', sa.Column('owner_user_id', sa.String(36), nullable=True))
    op.create_index('ix_monitor_rules_owner', 'monitor_rules', ['owner_user_id'])


def downgrade():
    op.drop_index('ix_monitor_rules_owner', table_name='monitor_rules')
    op.drop_column('monitor_rules', 'owner_user_id')
    op.drop_table('api_keys')
    op.drop_table('user_identities')
    op.drop_table('users')
