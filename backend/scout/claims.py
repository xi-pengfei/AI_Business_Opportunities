"""No LLM interpretation: authenticated sender + exact item code + affirmative reply."""

import json
import re
import time

from sqlalchemy import select

from scout.db import Session
from scout.models import Delivery, Item

CODE = re.compile(r"BO-([a-fA-F0-9]{12})", re.I)
AFFIRMATIVE = {
    "收到",
    "已收到",
    "认领",
    "我来跟进",
    "我来处理",
    "同意",
    "拿到信息了",
    "收到我来跟进",
}


def accept_claim(data, config, sessions=Session, now=None):
    # Called only by the authenticated DingTalk Stream callback, not an open HTTP endpoint.
    if (
        str(data.get("conversationType")) != "2"
        or not data.get("isInAtList")
        or data.get("conversationId") != config.dingtalk_conversation_id
        or data.get("robotCode") != config.dingtalk_robot_code
    ):
        return "ignored_context"
    sender = data.get("senderStaffId") or data.get("senderId")
    message_id = data.get("msgId")
    if (
        not isinstance(sender, str)
        or not sender
        or not isinstance(message_id, str)
        or not message_id
    ):
        return "ignored_identity"
    text = data.get("text")
    if not isinstance(text, dict) or not isinstance(text.get("content"), str):
        return "ignored_content"
    body = text["content"][:2000]
    reply = text.get("repliedMsg") if text.get("isReplyMsg") else None
    # Quote fields are a best-effort compatibility path. The explicit code path
    # works even when DingTalk clients omit quote metadata.
    quoted = json.dumps(reply, ensure_ascii=False)[:20000] if reply is not None else ""
    codes = {m.lower() for m in CODE.findall(body + " " + quoted)}
    normalized = CODE.sub("", body).replace("@AI商机智能体", "")
    normalized = re.sub(r"[\s，,。.!！：:；;]+", "", normalized)
    if normalized not in AFFIRMATIVE or len(codes) != 1:
        return "ignored_confirmation"
    with sessions() as db:
        row = db.scalar(
            select(Delivery)
            .where(
                Delivery.claim_code == codes.pop(),
                Delivery.conversation_id == data["conversationId"],
                Delivery.robot_code == data["robotCode"],
            )
            .with_for_update()
        )
        if row is None:
            return "unknown_item"
        if db.get(Item, row.item_id).information_kind == "customer_update":
            return "not_claimable"
        if row.status == "claimed":
            return "already_claimed"
        if row.status not in ("sending", "accepted", "sent", "read", "unknown"):
            return "not_sent"
        row.sent_at = row.sent_at or row.created_at
        row.error_code = None
        row.claimed_by_id = sender[:200]
        row.claimed_by_name = str(data.get("senderNick") or sender)[:120]
        row.claimed_at = now or time.time()
        row.claim_message_id = message_id[:500]
        row.status = "claimed"
        db.commit()
        return "claimed"
