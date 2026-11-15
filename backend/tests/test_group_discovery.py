from test_dingtalk import config

from scout.group_discovery import discover_group
from scout.models import DingTalkGroup


def test_explicit_new_group_discovery_does_not_change_binding(database):
    cfg = config()
    payload = {'conversationType': '2', 'conversationId': 'new-group', 'conversationTitle': '新群',
               'isInAtList': True, 'robotCode': 'robot', 'text': {'content': '获取群ID'}}
    assert discover_group(payload, cfg, database)
    assert discover_group(payload, cfg, database)
    assert cfg.dingtalk_conversation_id == 'group'
    with database() as db:
        assert db.get(DingTalkGroup, 'new-group').title == '新群'
    assert not discover_group({**payload, 'isInAtList': False}, cfg, database)
    assert not discover_group({**payload, 'robotCode': 'other'}, cfg, database)
    assert not discover_group({**payload, 'text': {'content': '收到'}}, cfg, database)


def test_group_ids_require_admin(client):
    assert client.get('/api/v1/dingtalk/groups', headers={'Authorization': 'Bearer test-display'}).status_code == 403
    assert client.get('/api/v1/dingtalk/groups').status_code == 200
