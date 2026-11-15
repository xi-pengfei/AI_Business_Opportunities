import json

import httpx
from sqlalchemy import select

from scout.assignments import assignment_facts
from scout.config import Settings
from scout.dingtalk import DingTalk, tick
from scout.models import Delivery, DeliveryGate, Document, Item


def config(**overrides):
    return Settings(
        _env_file=None,
        dingtalk_enabled=True,
        dingtalk_app_key="test-key",
        dingtalk_app_secret="test-secret",
        dingtalk_robot_code="robot",
        dingtalk_conversation_id="group",
        **overrides,
    )


def seed(database):
    with database() as db:
        db.add(DeliveryGate(id="dingtalk"))
        for n in range(2):
            doc = Document(
                identity=f"doc-{n}",
                url=f"https://example.com/{n}",
                title=f"需求{n}",
                raw_content="计划建设ERP系统。",
                content_kind="search_excerpt",
                content_hash=f"hash-{n}",
                provider="test",
            )
            db.add(doc)
            db.flush()
            db.add(
                Item(
                    id=f"item-{n}",
                    document_id=doc.id,
                    title=doc.title,
                    url=doc.url,
                    text=doc.raw_content,
                    fragments=[{"index": 0, "text": doc.raw_content}],
                    created_at=100 + n,
                    published_at="1970-01-01",
                    information_kind="opportunity",
                    ai_review={"decision": "buyer_demand"},
                )
            )
        db.commit()


class Transport:
    def __init__(self):
        self.sent = []
        self.readers = []
        self.fail = False

    def authenticate(self):
        pass

    def send(self, item, delivery):
        self.sent.append(item.id)
        if self.fail:
            raise httpx.ReadTimeout("test")
        return "msg-" + item.id

    def receipt(self, delivery):
        return {"sendStatus": "SUCCESS", "readUserIds": self.readers}


def test_only_explicit_claim_releases_exactly_one_next_item(database):
    from scout.claims import accept_claim

    seed(database)
    transport = Transport()
    cfg = config()
    assert tick(cfg, transport, database, 1000) == "accepted"
    with database() as db:
        row = db.get(Delivery, "item-0")
        code = row.claim_code
        facts = assignment_facts(db, False, 1000, True)
        assert (
            facts["pending_count"],
            facts["pushed_count"],
            facts["backlog_count"],
            facts["assigned_count"],
        ) == (1, 1, 2, 0)
    transport.readers = ["any-group-member"]
    assert tick(cfg, transport, database, 1031) == "waiting_claim"
    assert transport.sent == ["item-0"]
    payload = {
        "conversationType": "2",
        "conversationId": "group",
        "robotCode": "robot",
        "isInAtList": True,
        "senderStaffId": "member-1",
        "senderNick": "张三",
        "msgId": "reply-1",
        "text": {"content": "收到 BO-" + code},
    }
    assert accept_claim(payload, cfg, database, 1062) == "claimed"
    payload.update(senderStaffId="member-2", senderNick="李四", msgId="reply-2")
    assert accept_claim(payload, cfg, database, 1063) == "already_claimed"
    assert tick(cfg, transport, database, 1064) == "accepted"
    assert transport.sent == ["item-0", "item-1"]
    with database() as db:
        assert db.get(Delivery, "item-0").claimed_by_id == "member-1"
        assert db.get(Delivery, "item-1").claimed_at is None
        facts = assignment_facts(db, False, 1094, False)
        assert facts["backlog_count"] == 1
        assert facts["assigned_count"] == 1
        assert all(i["title"] == "已归集信息（展示模式已脱敏）" for i in facts["assigned_items"])
        assert all(
            i["claimed_by"] == ("群成员" if i["business_status"] == "claimed" else None)
            for i in facts["assigned_items"]
        )


def test_ambiguous_send_never_repeats_or_unblocks_next(database):
    seed(database)
    transport = Transport()
    transport.fail = True
    assert tick(config(), transport, database, 1000) == "unknown"
    transport.fail = False
    assert tick(config(), transport, database, 2000) == "unknown"
    assert transport.sent == ["item-0"]
    with database() as db:
        assert assignment_facts(db, False, 2000, True)["pending_count"] == 2
        assert len(db.scalars(select(Item)).all()) == 2


def test_disabled_delivery_never_contacts_dingtalk(database):
    transport = Transport()
    cfg = config().model_copy(update={"dingtalk_enabled": False})
    assert tick(cfg, transport, database) == "not_configured"
    assert transport.sent == []


def test_group_api_contract_and_token_cache():
    calls = []

    def handle(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("accessToken"):
            return httpx.Response(200, json={"accessToken": "test-token", "expireIn": 7200})
        assert request.headers["x-acs-dingtalk-access-token"] == "test-token"
        if request.url.path.endswith("/send"):
            return httpx.Response(200, json={"processQueryKey": "message-proof"})
        return httpx.Response(200, json={"sendStatus": "SUCCESS", "readUserIds": ["member"]})

    adapter = DingTalk(
        config(),
        httpx.Client(base_url="https://api.dingtalk.com", transport=httpx.MockTransport(handle)),
    )
    adapter.authenticate()
    adapter.authenticate()
    item = Item(
        title="系统需求",
        url="https://example.com",
        fragments=[{"text": "计划采购ERP系统。"}],
        created_at=100,
        published_at=None,
    )
    delivery = Delivery(conversation_id="group", robot_code="robot")
    delivery.message_id = adapter.send(item, delivery)
    assert len(calls) == 2
    assert calls[1][0] == "/v1.0/robot/groupMessages/send"
    assert calls[1][1]["openConversationId"] == "group"
    assert "userIds" not in calls[1][1]
    assert delivery.message_id == "message-proof"


def test_quote_claim_rejects_wrong_group_negation_ambiguous_code_and_plain_received(database):
    from scout.claims import accept_claim

    seed(database)
    cfg = config()
    tick(cfg, Transport(), database, 1000)
    with database() as db:
        code = db.get(Delivery, "item-0").claim_code
    p = {
        "conversationType": "2",
        "conversationId": "group",
        "robotCode": "robot",
        "isInAtList": True,
        "senderStaffId": "member",
        "senderNick": "张三",
        "msgId": "reply",
        "text": {"content": "收到"},
    }
    assert accept_claim(p, cfg, database) == "ignored_confirmation"
    p["text"] = {"content": "不认领 BO-" + code}
    assert accept_claim(p, cfg, database) == "ignored_confirmation"
    p["text"] = {"content": "收到 BO-" + code + " BO-ffffffffffff"}
    assert accept_claim(p, cfg, database) == "ignored_confirmation"
    p["text"] = {
        "content": "我来跟进",
        "isReplyMsg": True,
        "repliedMsg": {"content": "商机编号：BO-" + code},
    }
    p["conversationId"] = "other-group"
    assert accept_claim(p, cfg, database) == "ignored_context"
    p["conversationId"] = "group"
    assert accept_claim(p, cfg, database) == "claimed"
    assert accept_claim(p, cfg, database) == "already_claimed"


def test_claim_arriving_before_send_response_is_not_overwritten(database):
    from scout.claims import accept_claim

    seed(database)
    cfg = config()

    class EarlyReply(Transport):
        def send(self, item, delivery):
            payload = {
                "conversationType": "2",
                "conversationId": "group",
                "robotCode": "robot",
                "isInAtList": True,
                "senderStaffId": "member",
                "senderNick": "张三",
                "msgId": "early",
                "text": {"content": "收到 BO-" + delivery.claim_code},
            }
            assert accept_claim(payload, cfg, database, 1001) == "claimed"
            return "msg-proof"

    assert tick(cfg, EarlyReply(), database, 1000) == "claimed"
    with database() as db:
        row = db.get(Delivery, "item-0")
        assert row.status == "claimed"
        assert row.message_id == "msg-proof"


def test_bulletin_and_unknown_date_never_push(database):
    seed(database)
    with database.begin() as db:
        db.get(Item, "item-0").information_kind = "bulletin"
        db.get(Item, "item-1").published_at = None
    transport = Transport()
    assert tick(config(), transport, database, 1000) == "empty"
    assert transport.sent == []


def test_archived_unclaimed_message_releases_gate_but_keeps_delivery(database):
    seed(database)
    transport = Transport()
    assert tick(config(), transport, database, 1000) == "accepted"
    with database.begin() as db:
        db.get(Item, "item-0").quality_status = "archived"
    assert tick(config(), transport, database, 1100) == "accepted"
    assert transport.sent == ["item-0", "item-1"]
    with database() as db:
        assert db.get(Delivery, "item-0").status == "accepted"


def test_restored_delivery_is_visible_without_fabricated_receipt_or_resend(database):
    seed(database)
    with database.begin() as db:
        db.add(
            Delivery(
                item_id="item-0",
                conversation_id="group",
                robot_code="robot",
                status="restored",
                error_code="historical_receipt_unavailable",
            )
        )
        db.get(Item, "item-1").information_kind = "bulletin"
    transport = Transport()
    assert tick(config(), transport, database, 1000) == "empty"
    assert transport.sent == []
    with database() as db:
        rows = assignment_facts(db, False, 1000, True)["assigned_items"]
        assert rows[0]["delivery_status"] == "restored"
        assert rows[0]["sent_at"] is None
        assert rows[0]["claimed_at"] is None


def test_customer_news_does_not_wait_for_or_accept_claims(database):
    from scout.claims import accept_claim
    from scout.dingtalk import tick_news
    from scout.information import item_record

    seed(database)
    transport, cfg = Transport(), config()
    assert tick(cfg, transport, database, 1000) == "accepted"
    with database.begin() as db:
        db.add(DeliveryGate(id="customer_news"))
        i = db.get(Item, "item-1")
        i.source_type, i.information_kind = "customer_watch", "customer_update"
    assert tick(cfg, transport, database, 1001) == "waiting_claim"
    assert tick_news(cfg, transport, database, 1001) == "sent"
    assert tick_news(cfg, transport, database, 1002) == "empty"
    assert transport.sent == ["item-0", "item-1"]
    with database() as db:
        assert db.get(DeliveryGate, "dingtalk").current_item_id == "item-0"
        d = db.get(Delivery, "item-1")
        code = d.claim_code
        row = item_record(db, db.get(Item, "item-1"))
        assert row["business_status"] == "sent" and row["claimed_by"] is None
        assert row["source_name"] == "监控"
    result = accept_claim(
        {
            "conversationType": "2",
            "isInAtList": True,
            "conversationId": "group",
            "robotCode": "robot",
            "senderId": "sender",
            "senderNick": "staff",
            "msgId": "reply",
            "text": {"content": "收到 BO-" + code},
        },
        cfg,
        database,
        1003,
    )
    assert result == "not_claimable"


def test_news_unknown_send_is_not_resent_and_does_not_block_other_news(database):
    from scout.dingtalk import tick_news

    seed(database)
    with database.begin() as db:
        db.add(DeliveryGate(id="customer_news"))
        for i in db.scalars(select(Item)):
            i.source_type, i.information_kind = "customer_watch", "customer_update"
    transport = Transport()
    transport.fail = True
    assert tick_news(config(), transport, database, 1000) == "unknown"
    transport.fail = False
    assert tick_news(config(), transport, database, 1001) == "sent"
    assert tick_news(config(), transport, database, 1002) == "empty"
    assert transport.sent == ["item-0", "item-1"]


def test_customer_broadcast_message_has_source_but_no_claim_instruction(database):
    seed(database)
    with database() as db:
        item = db.get(Item, "item-0")
        item.source_type = "customer_watch"
        item.information_kind = "customer_update"
        delivery = Delivery(
            item_id=item.id, conversation_id="group", robot_code="robot", claim_code="abcdef123456"
        )
        transport = DingTalk(config())
        captured = []
        transport.request = lambda path, body: (
            captured.append(body) or {"processQueryKey": "message"}
        )
        assert transport.send(item, delivery) == "message"
        content = json.loads(captured[0]["msgParam"])["content"]
        assert "信息来源：监控" in content
        assert "BO-" not in content and "认领方式" not in content


def test_monitor_opportunity_message_requires_claim(database):
    seed(database)
    with database() as db:
        item = db.get(Item, "item-0")
        item.source_type = "customer_watch"
        item.information_kind = "opportunity"
        delivery = Delivery(item_id=item.id, conversation_id="group", robot_code="robot", claim_code="abc123")
        transport = DingTalk(config())
        captured = []
        transport.request = lambda path, body: captured.append(body) or {"processQueryKey": "test"}
        transport.send(item, delivery)
        content = json.loads(captured[0]["msgParam"])["content"]
        assert "信息来源：监控" in content and "商机编号" in content and "认领方式" in content
        assert "无需认领" not in content


def test_send_failure_diagnostics_do_not_expose_payloads():
    from scout.dingtalk import send_error
    request = httpx.Request("POST", "https://example.com/private")
    response = httpx.Response(429, request=request, text="secret payload")
    error = httpx.HTTPStatusError("secret", request=request, response=response)
    assert send_error(error) == "send_http_429"
    assert send_error(httpx.ReadTimeout("secret")) == "send_timeout"
    assert send_error(httpx.ConnectError("secret")) == "send_connection_error"
    assert send_error(ValueError("missing_message_id")) == "missing_message_id"
    assert send_error(ValueError("secret")) == "send_result_unknown"
