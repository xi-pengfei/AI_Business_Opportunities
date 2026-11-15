"""Allow multiple customer reference URLs without trusting entire media domains."""
import sqlalchemy as sa
from alembic import op

revision = 'q017_customer_urls'
down_revision = 'p016_group_discovery'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('monitor_rules', 'query', type_=sa.Text(), existing_type=sa.String(500))
    op.add_column('customers', sa.Column('reference_urls', sa.JSON(), nullable=False, server_default='[]'))
    op.execute("UPDATE customers SET reference_urls=json_build_array(website) WHERE website IS NOT NULL")


def downgrade():
    op.drop_column('customers', 'reference_urls')
