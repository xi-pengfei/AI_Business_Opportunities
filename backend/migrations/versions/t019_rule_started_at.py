"""Track when a rule last started collecting, for runtime display."""
import sqlalchemy as sa
from alembic import op

revision = 't019_rule_started_at'
down_revision = 's019_console_token'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('monitor_rules', sa.Column('started_at', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('monitor_rules', 'started_at')
