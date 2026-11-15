"""One-time invite links for binding DingTalk identities to pre-created accounts."""
import sqlalchemy as sa
from alembic import op

revision = 'v021_invite_tokens'
down_revision = 'u020_users_auth'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'invite_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('token', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False, server_default='dingtalk'),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('used_at', sa.Float(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table('invite_tokens')
