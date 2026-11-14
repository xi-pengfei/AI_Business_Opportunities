"""Keep social demand source explicit in shared library and cleanup."""
import sqlalchemy as sa
from alembic import op

revision = "j810_social_demand"
down_revision = "i709_customer_watch"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("source_type", sa.String(30), nullable=False, server_default="public_tender"))


def downgrade():
    op.drop_column("information_items", "source_type")
