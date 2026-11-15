"""Durable social-demand AI review and quarantine for existing unreviewed candidates."""
import sqlalchemy as sa
from alembic import op

revision = "m013_social_ai_review"
down_revision = "l012_backlog_samples"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("ai_review", sa.JSON(), nullable=False, server_default="{}"))
    op.execute("UPDATE information_items SET quality_status='review_pending', quality_reason='ai_review_required' WHERE source_type='social_demand' AND quality_status='active' AND is_demo=false")


def downgrade():
    # Do not reactivate unreviewed information on rollback.
    op.drop_column("information_items", "ai_review")
