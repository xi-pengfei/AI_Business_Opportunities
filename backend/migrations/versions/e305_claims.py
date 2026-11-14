"""Explicit group-message claims supersede read-receipt release."""

import sqlalchemy as sa
from alembic import op

revision = "e305_claims"
down_revision = "d204_deliveries"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("information_deliveries", sa.Column("claim_code", sa.String(20)))
    op.create_unique_constraint("uq_delivery_claim_code", "information_deliveries", ["claim_code"])
    op.add_column("information_deliveries", sa.Column("claimed_by_id", sa.String(200)))
    op.add_column("information_deliveries", sa.Column("claimed_by_name", sa.String(120)))
    op.add_column("information_deliveries", sa.Column("claimed_at", sa.Float()))
    op.add_column("information_deliveries", sa.Column("claim_message_id", sa.String(500)))
    op.create_unique_constraint(
        "uq_delivery_claim_message", "information_deliveries", ["claim_message_id"]
    )


def downgrade():
    op.drop_constraint("uq_delivery_claim_message", "information_deliveries", type_="unique")
    op.drop_constraint("uq_delivery_claim_code", "information_deliveries", type_="unique")
    for name in [
        "claim_message_id",
        "claimed_at",
        "claimed_by_name",
        "claimed_by_id",
        "claim_code",
    ]:
        op.drop_column("information_deliveries", name)
