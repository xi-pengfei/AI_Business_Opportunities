"""Retain filtered evidence and explicit geographic/date provenance."""
import sqlalchemy as sa
from alembic import op

revision = "b902_quality"
down_revision = "a1042f8d47dc"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("quality_status", sa.String(20), server_default="active", nullable=False))
    for name, length in [("quality_reason", 50), ("region", 20), ("region_evidence", 100), ("published_at", 30)]:
        op.add_column("information_items", sa.Column(name, sa.String(length), nullable=True))


def downgrade():
    for name in ["quality_status", "quality_reason", "region", "region_evidence", "published_at"]:
        op.drop_column("information_items", name)
