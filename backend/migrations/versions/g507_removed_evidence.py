"""Content-free fingerprints prevent deleted deliveries from being collected again."""
import sqlalchemy as sa
from alembic import op

revision = "g507_removed_evidence"
down_revision = "f406_routing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("removed_evidence", sa.Column("url_hash", sa.String(64), primary_key=True),
                    sa.Column("content_hash", sa.String(64), nullable=False))
    op.create_index("ix_removed_evidence_content_hash", "removed_evidence", ["content_hash"])


def downgrade():
    op.drop_table("removed_evidence")
