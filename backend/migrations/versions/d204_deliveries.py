"""DingTalk group deliveries and a durable one-unread-message gate."""

import sqlalchemy as sa
from alembic import op

revision = "d204_deliveries"
down_revision = "c103_fragments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "information_deliveries",
        sa.Column(
            "item_id", sa.String(36), sa.ForeignKey("information_items.id"), primary_key=True
        ),
        sa.Column("conversation_id", sa.String(300), nullable=False),
        sa.Column("robot_code", sa.String(120), nullable=False),
        sa.Column("recipient", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message_id", sa.String(500), unique=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("sent_at", sa.Float()),
        sa.Column("read_at", sa.Float()),
        sa.Column("next_check_at", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(60)),
    )
    op.create_table(
        "delivery_gates",
        sa.Column("id", sa.String(30), primary_key=True),
        sa.Column("current_item_id", sa.String(36), sa.ForeignKey("information_items.id")),
    )
    op.execute("INSERT INTO delivery_gates (id) VALUES ('dingtalk')")


def downgrade():
    op.drop_table("delivery_gates")
    op.drop_table("information_deliveries")
