"""Literal source fragments, provenance and information categories."""
import sqlalchemy as sa
from alembic import op

revision = "c103_fragments"
down_revision = "b902_quality"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("fragments", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("information_items", sa.Column("category", sa.String(30), server_default="其他信息", nullable=False))


def downgrade():
    op.drop_column("information_items", "category")
    op.drop_column("information_items", "fragments")
