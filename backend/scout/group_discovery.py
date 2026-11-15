"""Receive explicit discovery commands; never silently rebind or send messages."""
import time

from scout.db import Session
from scout.models import DingTalkGroup


def discover_group(data, config, sessions=Session):
    content = data.get('text', {})
    content = content.get('content', '') if isinstance(content, dict) else ''
    if not isinstance(content, str):
        return False
    content = content.replace('@AI商机智能体', '').strip()
    group_id = data.get('conversationId')
    if (content != '获取群ID' or str(data.get('conversationType')) != '2'
            or data.get('isInAtList') is not True
            or data.get('robotCode') != config.dingtalk_robot_code
            or not isinstance(group_id, str) or not 1 <= len(group_id) <= 300):
        return False
    with sessions.begin() as db:
        db.merge(DingTalkGroup(conversation_id=group_id,
                              title=str(data.get('conversationTitle') or '未提供群名')[:200],
                              robot_code=config.dingtalk_robot_code, requested_at=time.time()))
    return True
