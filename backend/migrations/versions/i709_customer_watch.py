"""Customer targets and independently routed customer signals."""
import sqlalchemy as sa
from alembic import op

revision = "i709_customer_watch"
down_revision = "h608_search_cursors"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("website", sa.Text()),
        sa.Column("identity_source", sa.Text()),
        sa.Column("created_at", sa.Float(), nullable=False))
    op.add_column("monitor_rules", sa.Column("source_type", sa.String(30), nullable=False, server_default="public_tender"))
    op.add_column("monitor_rules", sa.Column("customer_id", sa.String(36)))
    op.create_foreign_key("fk_rules_customer", "monitor_rules", "customers", ["customer_id"], ["id"])
    op.create_unique_constraint("uq_rules_customer", "monitor_rules", ["customer_id"])
    op.create_table("customer_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(30), nullable=False),
        sa.Column("matched_name", sa.String(120), nullable=False),
        sa.Column("fragments", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.String(30)),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("quality_reason", sa.String(50)),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("customer_id", "url"),
        sa.UniqueConstraint("customer_id", "content_hash"))
    op.create_index("ix_customer_signals_customer_id", "customer_signals", ["customer_id"])
    op.create_index("ix_customer_signals_created_at", "customer_signals", ["created_at"])


def downgrade():
    op.drop_table("customer_signals")
    op.drop_constraint("uq_rules_customer", "monitor_rules")
    op.drop_constraint("fk_rules_customer", "monitor_rules", type_="foreignkey")
    op.drop_column("monitor_rules", "customer_id")
    op.drop_column("monitor_rules", "source_type")
    op.drop_table("customers")
