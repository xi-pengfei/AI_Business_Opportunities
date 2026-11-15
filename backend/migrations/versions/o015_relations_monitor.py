"""Keep semantic duplicate/update relations and origin URLs; route monitoring through AI."""
import sqlalchemy as sa
from alembic import op

revision = "o015_relations_monitor"
down_revision = "n014_all_opportunity_review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_items", sa.Column("related_item_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_information_related", "information_items", "information_items", ["related_item_id"], ["id"])
    op.create_index("ix_information_items_related_item_id", "information_items", ["related_item_id"])
    op.add_column("information_items", sa.Column("relation_kind", sa.String(20), nullable=True))
    op.add_column("information_items", sa.Column("source_urls", sa.JSON(), nullable=False, server_default="[]"))
    op.execute("""UPDATE information_items SET quality_status='review_pending', quality_reason='ai_review_required'
        WHERE is_demo=false AND source_type='customer_watch' AND information_kind='customer_update'
        AND quality_status='active' AND COALESCE(ai_review->>'decision','')=''""")


def downgrade():
    op.drop_column("information_items", "source_urls")
    op.drop_column("information_items", "relation_kind")
    op.drop_index("ix_information_items_related_item_id", table_name="information_items")
    op.drop_constraint("fk_information_related", "information_items", type_="foreignkey")
    op.drop_column("information_items", "related_item_id")
