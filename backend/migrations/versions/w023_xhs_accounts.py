"""Multiple xiaohongshu accounts: each connector instance gets its own rule.

Creates xhs_accounts, links monitor_rules.xhs_account_id, and folds the legacy
single-connector config (.env) into a default account so existing rules keep
running under the new per-account model.
"""
import os
import time

import sqlalchemy as sa
from alembic import op

revision = 'w023_xhs_accounts'
down_revision = 'w022_drop_customer_site_columns'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'xhs_accounts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('token', sa.String(500), nullable=False, server_default=''),
        sa.Column('owner_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.Float(), nullable=False),
    )
    op.add_column('monitor_rules', sa.Column('xhs_account_id', sa.String(36),
                  sa.ForeignKey('xhs_accounts.id'), nullable=True))
    # 存量单连接器（.env 配置）收编为默认账号，老规则保持运行
    url = (os.environ.get('XIAOHONGSHU_URL') or '').strip()
    if url:
        import uuid
        account_id = str(uuid.uuid4())
        op.execute(sa.text(
            "INSERT INTO xhs_accounts (id, name, url, token, owner_user_id, enabled, created_at) "
            "VALUES (:id, :name, :url, :token, NULL, true, :created)"
        ).bindparams(id=account_id, name='默认账号', url=url,
                     token=os.environ.get('XIAOHONGSHU_TOKEN') or '', created=time.time()))
        op.execute(sa.text(
            "UPDATE monitor_rules SET xhs_account_id = :account "
            "WHERE provider = 'xiaohongshu' AND xhs_account_id IS NULL"
        ).bindparams(account=account_id))


def downgrade():
    op.drop_column('monitor_rules', 'xhs_account_id')
    op.drop_table('xhs_accounts')
