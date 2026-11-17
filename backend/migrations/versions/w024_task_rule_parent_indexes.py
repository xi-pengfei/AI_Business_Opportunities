"""tasks 表加 rule_id / parent_id 索引：采集器状态与批次明细按规则查任务，
15 万行时无索引每次全表扫，快照接口被拖到数秒。"""

revision = "w024_task_rule_parent_indexes"
down_revision = "w023_xhs_accounts"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_index("ix_tasks_rule_id", "tasks", ["rule_id"])
    op.create_index("ix_tasks_parent_id", "tasks", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_parent_id", table_name="tasks")
    op.drop_index("ix_tasks_rule_id", table_name="tasks")
