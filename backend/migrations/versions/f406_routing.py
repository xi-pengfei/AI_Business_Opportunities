"""Separate unverified industry information from push-eligible demand evidence."""
import sqlalchemy as sa
from alembic import op

revision = "f406_routing"
down_revision = "e305_claims"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("information_kind", sa.String(20), nullable=False, server_default="bulletin"))


def downgrade():
    op.drop_column("information_items", "information_kind")
