import json

import httpx
import pytest
from sqlalchemy import select
from test_dingtalk import Transport, config
from test_dingtalk import seed as original_seed

from scout.ai_review import classify, tick
from scout.config import Settings
from scout.dingtalk import tick as send_tick
from scout.models import Item


def seed(database):
    original_seed(database)
    with database.begin() as db:
        for item in db.scalars(select(Item)):
            item.published_at = "2000-01-01"
            item.created_at = 946684800


def model_config():
    return Settings(_env_file=None, deepseek_api_key="test-key")


def client_for(verdict):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]})))


def test_no_key_never_calls_model(database):
    assert tick(Settings(_env_file=None, deepseek_api_key=""), database) == "waiting_configuration"


def test_approval_requires_literal_evidence():
    with client_for({"decision": "buyer_demand", "reason": "买方", "evidence": "不存在的需求证据"}) as client:
        with pytest.raises(ValueError, match="unsupported_ai_approval"):
            classify("标题", "我们提供开发服务", model_config(), client)
    with client_for({"decision": "buyer_demand", "reason": "买方寻找团队", "evidence": "我们工厂想找团队开发MES"}) as client:
        assert classify("求助", "我们工厂想找团队开发MES", model_config(), client)["decision"] == "buyer_demand"


def test_quarantine_failure_and_review(database):
    seed(database)
    with database.begin() as db:
        item = db.get(Item, "item-0")
        item.source_type, item.quality_status = "social_demand", "review_pending"
    def fail(*args):
        raise TimeoutError("private text must not be persisted")
    for now in (946685800, 946686800, 946687800):
        tick(model_config(), database, reviewer=fail, now=now)
    with database() as db:
        item = db.get(Item, "item-0")
        assert item.quality_status == "review_required"
        assert item.ai_review["attempts"] == 3
        assert "private" not in json.dumps(item.ai_review)


def test_seller_archived_and_other_source_can_send(database):
    seed(database)
    with database.begin() as db:
        item = db.get(Item, "item-0")
        item.source_type, item.quality_status = "social_demand", "review_pending"
    verdict = {"decision": "seller_promotion", "reason": "提供服务", "evidence": ""}
    assert tick(model_config(), database, reviewer=lambda *args: verdict, now=946685800) == "seller_promotion"
    with database() as db:
        assert db.get(Item, "item-0").quality_status == "archived"
    transport = Transport()
    send_tick(config(), transport, database, now=946685800)
    assert transport.sent == ["item-1"]


def test_old_active_social_cannot_bypass_review(database):
    seed(database)
    with database.begin() as db:
        for item in db.scalars(select(Item)):
            item.source_type = "social_demand"
            item.ai_review = {}
    transport = Transport()
    assert send_tick(config(), transport, database, now=946685800) == "empty"
    assert not transport.sent


def test_delayed_approval_enters_feed_without_changing_capture_time(database, client):
    seed(database)
    with database.begin() as db:
        item = db.get(Item, "item-0")
        item.source_type, item.quality_status = "social_demand", "review_pending"
    cursor = 946685500
    assert client.get(f"/api/v1/display/feed?after={cursor}").json()["items"] == []
    verdict = {"decision": "buyer_demand", "reason": "买方需求", "evidence": "计划建设ERP系统。"}
    tick(model_config(), database, reviewer=lambda *args: verdict, now=946685800)
    result = client.get(f"/api/v1/display/feed?after={cursor}").json()
    assert [i["id"] for i in result["items"]] == ["item-0"]
    assert result["items"][0]["created_at"] == 946684800
    assert result["after"] == 946685800
    assert client.get(f'/api/v1/display/feed?after={result["after"]}&after_id=item-0').json()["items"] == []


@pytest.mark.parametrize("source", ["public_tender", "social_demand", "future_srm", "customer_watch"])
def test_all_opportunities_require_model_approval(database, client, source):
    seed(database)
    with database.begin() as db:
        for item in db.scalars(select(Item)):
            item.source_type = source
            item.ai_review = {}
            item.quality_status = "active"  # A stale script cannot bypass the read/send gate.
    assert client.get("/api/v1/display/feed?after=0").json()["items"] == []
    transport = Transport()
    assert send_tick(config(), transport, database, now=946685800) == "empty"
    with database.begin() as db:
        db.get(Item, "item-0").quality_status = "review_pending"
    verdict = {"decision": "buyer_demand", "reason": "有采购需求", "evidence": "计划建设ERP系统。"}
    assert tick(model_config(), database, reviewer=lambda *args: verdict, now=946685800) == "buyer_demand"
    assert send_tick(config(), transport, database, now=946685800) == "accepted"
    assert transport.sent == ["item-0"]


def test_network_ingest_is_quarantined_before_review(database):
    import time
    from datetime import datetime

    from scout import service
    from scout.quality import ZONE
    with database.begin() as db:
        task = service.enqueue(db, kind="ingest", key="public-review-test", payload={
            "source_type": "public_tender", "provider": "searxng", "url": "https://example.com/new",
            "title": "某学院ERP系统采购公告", "raw_content": "某学院拟采购ERP系统，现发布招标公告。",
            "published_at": datetime.fromtimestamp(time.time(), ZONE).date().isoformat(),
            "content_kind": "search_excerpt"})
        tid = task.id
    service.execute(tid)
    with database() as db:
        item = db.scalar(select(Item).where(Item.url == "https://example.com/new"))
        assert item.quality_status == "review_pending"
        assert not item.ai_review


def test_nonliteral_quote_gets_one_bounded_correction():
    raw = '本公司拟采购MES生产管理系统，欢迎供应商参与报价。'
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        evidence = '本公司拟采购……欢迎供应商参与报价。' if len(calls) == 1 else raw
        verdict = {'decision': 'buyer_demand', 'reason': '明确采购', 'evidence': evidence}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(verdict)}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert classify('采购', raw, model_config(), client)['evidence'] == raw
    assert len(calls) == 2
    assert '禁止省略号' in calls[1]['messages'][-1]['content']
