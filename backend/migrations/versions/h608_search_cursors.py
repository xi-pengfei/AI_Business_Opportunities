"""Persist independent search progress and source cooldowns."""
import sqlalchemy as sa
from alembic import op

revision = "h608_search_cursors"
down_revision = "g507_removed_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("search_cursors",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("rule_id",sa.String(36),sa.ForeignKey("monitor_rules.id"),nullable=False),
        sa.Column("config_version",sa.Integer(),nullable=False),
        sa.Column("query",sa.String(500),nullable=False),
        sa.Column("engine",sa.String(40),nullable=False),
        sa.Column("page",sa.Integer(),nullable=False),
        sa.Column("empty_streak",sa.Integer(),nullable=False),
        sa.Column("signature",sa.String(64)),
        sa.Column("next_at",sa.Float(),nullable=False),
        sa.Column("last_front_at",sa.Float(),nullable=False),
        sa.Column("last_result_at",sa.Float()),
        sa.Column("outcome",sa.String(40),nullable=False),
        sa.UniqueConstraint("rule_id","config_version","query","engine"))
    op.create_index("ix_search_cursors_rule_id","search_cursors",["rule_id"])
    op.create_index("ix_search_cursors_next_at","search_cursors",["next_at"])


def downgrade():
    op.drop_table("search_cursors")
