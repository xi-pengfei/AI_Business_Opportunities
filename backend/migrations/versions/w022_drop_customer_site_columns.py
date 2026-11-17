"""Drop legacy customer website/identity_source columns.

q017_customer_urls already folded website into reference_urls; identity_source
was never consumed anywhere. Identity matching is name/alias hit in the text.
"""
import sqlalchemy as sa
from alembic import op

revision = 'w022_drop_customer_site_columns'
down_revision = 'v021_invite_tokens'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('customers', 'identity_source')
    op.drop_column('customers', 'website')


def downgrade():
    op.add_column('customers', sa.Column('website', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('identity_source', sa.Text(), nullable=True))
