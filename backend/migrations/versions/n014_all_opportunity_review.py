"""All live business opportunities require model review, regardless of source."""
from alembic import op

revision = "n014_all_opportunity_review"
down_revision = "m013_social_ai_review"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE information_items SET quality_status='review_pending',
        quality_reason='ai_review_required'
        WHERE is_demo=false
        AND information_kind IN ('opportunity','demand') AND quality_status='active'
        AND COALESCE(ai_review->>'decision','') != 'buyer_demand'""")


def downgrade():
    # Never turn unaudited candidates into live opportunities on rollback.
    pass
