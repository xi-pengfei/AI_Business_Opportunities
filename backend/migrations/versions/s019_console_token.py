"""Persist rotated console access tokens so they survive restarts."""
import sqlalchemy as sa
from alembic import op

revision = 's019_console_token'
down_revision = 'r018_product_rules'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'console_tokens',
        sa.Column('purpose', sa.String(30), primary_key=True),
        sa.Column('token', sa.String(120), nullable=False),
        sa.Column('rotated_at', sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table('console_tokens')
