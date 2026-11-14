"""One group message at a time. Only an explicit authenticated claim opens the gate."""

import json
import logging
import time
from datetime import datetime

import httpx
from sqlalchemy import select

from scout.assignments import pending_items
from scout.config import settings
from scout.db import Session
from scout.models import Delivery, DeliveryGate, Item
from scout.quality import ZONE


class DingTalk:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or httpx.Client(base_url="https://api.dingtalk.com", timeout=20)
        self.token = ""
        self.expires = 0

    def authenticate(self):
        if self.token and time.time() < self.expires:
            return
        result = self.client.post(
            "/v1.0/oauth2/accessToken",
            json={
                "appKey": self.config.dingtalk_app_key,
                "appSecret": self.config.dingtalk_app_secret,
            },
        )
        result.raise_for_status()
        body = result.json()
        self.token = body["accessToken"]
        self.expires = time.time() + max(0, int(body.get("expireIn", 7200)) - 120)

    def request(self, path, body):
        response = self.client.post(
            path, json=body, headers={"x-acs-dingtalk-access-token": self.token}
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errcode", 0) != 0:
            raise ValueError("dingtalk_rejected")
        return data

    def send(self, item, delivery):
        captured = datetime.fromtimestamp(item.created_at, ZONE).strftime("%Y-%m-%d %H:%M:%S")
        content = "\n".join(
            [
                f"商机编号：BO-{delivery.claim_code}",
                item.title[:500],
                *[f["text"] for f in item.fragments],
                "原始网址：" + item.url[:2500],
                "新闻时间：" + (item.published_at or "未提供"),
                "采集时间：" + captured,
                "认领方式：引用本消息并 @AI商机智能体 回复 收到 / 我来跟进。若引用信息未传入，请回复：收到 BO-"
                + str(delivery.claim_code),
            ]
        )
        result = self.request(
            "/v1.0/robot/groupMessages/send",
            {
                "robotCode": delivery.robot_code,
                "openConversationId": delivery.conversation_id,
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": content}, ensure_ascii=False),
            },
        )
        message_id = result.get("processQueryKey")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("missing_message_id")
        return message_id


def configured(config):
    return all(
        (
            config.dingtalk_app_key,
            config.dingtalk_app_secret,
            config.dingtalk_robot_code,
            config.dingtalk_conversation_id,
        )
    )


def tick(config, transport, sessions=Session, now=None):
    now = now or time.time()
    if not config.dingtalk_enabled or not configured(config):
        return "not_configured"
    # Authentication failure occurs before a claim and never consumes an item.
    transport.authenticate()
    with sessions() as db:
        gate = db.scalar(
            select(DeliveryGate).where(DeliveryGate.id == "dingtalk").with_for_update()
        )
        if gate is None:
            raise RuntimeError("delivery_migration_required")
        if gate.current_item_id:
            current = db.get(Delivery, gate.current_item_id)
            if current.status in ("sending", "unknown", "failed"):
                if current.status == "sending" and now - current.created_at > 90:
                    current.status = "unknown"
                    current.error_code = "interrupted_send"
                    db.commit()
                return current.status
            if current.status != "claimed":
                # Reading alone never claims ownership or releases the next item.
                return "waiting_claim"
            gate.current_item_id = None
        item = db.scalar(
            pending_items(False)
            .where(~Item.id.in_(select(Delivery.item_id)))
            .order_by(Item.created_at, Item.id)
            .limit(1)
        )
        if item is None:
            db.commit()
            return "empty"
        delivery = Delivery(
            item_id=item.id,
            conversation_id=config.dingtalk_conversation_id,
            robot_code=config.dingtalk_robot_code,
            recipient=config.dingtalk_group_name,
            status="sending",
            created_at=now,
            next_check_at=now,
        )
        db.add(delivery)
        gate.current_item_id = item.id
        db.commit()  # Durable claim before the external side effect.
        try:
            message_id = transport.send(item, delivery)
            db.refresh(delivery)
            delivery.message_id = message_id
            delivery.sent_at = delivery.sent_at or now
            if delivery.status != "claimed":
                delivery.status = "accepted"
        except Exception:
            db.refresh(delivery)
            if delivery.status != "claimed":
                delivery.status = "unknown"
                delivery.error_code = "send_result_unknown"
        db.commit()
        return delivery.status


def main():
    config = settings()
    transport = DingTalk(config)
    while True:
        try:
            tick(config, transport)
        except Exception as exc:
            logging.warning("notification tick failed (%s)", type(exc).__name__)
        time.sleep(5)


if __name__ == "__main__":
    main()
