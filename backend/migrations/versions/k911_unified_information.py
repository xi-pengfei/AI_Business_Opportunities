"""Project customer evidence into the shared flow and isolate broadcasts."""

from alembic import op

revision = "k911_unified_information"
down_revision = "j810_social_demand"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("INSERT INTO delivery_gates (id) VALUES ('customer_news')")
    op.execute("""INSERT INTO information_items
      (id,document_id,title,url,text,fragments,category,source_type,information_kind,contacts,
       quality_status,quality_reason,published_at,is_demo,created_at)
      SELECT s.id,s.document_id,d.title,s.url,d.raw_content,s.fragments,s.topic,'customer_watch',
       'customer_update','[]',s.quality_status,s.quality_reason,s.published_at,false,s.created_at
      FROM customer_signals s JOIN document_versions d ON d.id=s.document_id
      WHERE NOT EXISTS (SELECT 1 FROM information_items i WHERE i.document_id=s.document_id)
    """)


def downgrade():
    # Keep customer information and delivery history; rollback must not erase business data.
    op.execute("DELETE FROM delivery_gates WHERE id='customer_news'")
