"""Store independent product aliases and editable search actions."""
import sqlalchemy as sa
from alembic import op

revision = 'r018_product_rules'
down_revision = 'q017_customer_urls'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('monitor_rules', sa.Column('search_spec', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('monitor_rules', 'search_spec')
