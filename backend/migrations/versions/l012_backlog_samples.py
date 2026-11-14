"""Persist actual business backlog observations."""

import sqlalchemy as sa
from alembic import op

revision = "l012_backlog_samples"
down_revision = "k911_unified_information"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "business_backlog_samples",
        sa.Column("minute", sa.Integer(), primary_key=True),
        sa.Column("is_demo", sa.Boolean(), primary_key=True),
        sa.Column("pending", sa.Integer(), nullable=False),
        sa.Column("waiting_claim", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("business_backlog_samples")
