"""Persist explicitly requested robot group IDs, without changing the target group."""
import sqlalchemy as sa
from alembic import op

revision = 'p016_group_discovery'
down_revision = 'o015_relations_monitor'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('dingtalk_discovered_groups',
                    sa.Column('conversation_id', sa.String(300), primary_key=True),
                    sa.Column('title', sa.String(200), nullable=False),
                    sa.Column('robot_code', sa.String(120), nullable=False),
                    sa.Column('requested_at', sa.Float(), nullable=False))


def downgrade():
    op.drop_table('dingtalk_discovered_groups')
