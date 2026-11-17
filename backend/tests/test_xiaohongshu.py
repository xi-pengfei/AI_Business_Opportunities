from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from scout import service, xiaohongshu
from scout.models import DeliveryGate, Item, Rule, Task
from scout.policies import describe_social_demand
from scout.providers import ProviderError
from scout.quality import ZONE

NOTE = "1234567890abcdef12345678"
RAW = "公司想做一个订单管理系统，求推荐靠谱的软件开发团队，能对接ERP并自动对账。"


def today():
    return datetime.now(ZONE).date().isoformat()


def test_social_admission_rejects_ads_and_old_posts():
    result = describe_social_demand("找软件开发团队", RAW, today())
    assert result["information_kind"] == "demand" and result["quality_status"] == "active"
    assert result["fragments"] and all(f["text"] in RAW for f in result["fragments"])
    assert (
        describe_social_demand(
            "找软件开发团队？专业承接", RAW + "专业团队承接APP开发，欢迎咨询。", today()
        )["information_kind"]
        == "bulletin"
    )
    assert (
        describe_social_demand("订单系统教程", "教你搭建一个软件系统", today())["information_kind"]
        == "bulletin"
    )
    assert describe_social_demand("找开发", RAW, None)["quality_reason"] == "unverified_date"
    old = (datetime.now(ZONE) - timedelta(days=31)).date().isoformat()
    assert describe_social_demand("找开发", RAW, old)["quality_status"] == "archived"


def test_note_parsing_checks_ids_and_preserves_publication_time(monkeypatch):
    def request(config, method, path, body=None):
        if path == "/login/status":
            return {"is_logged_in": True}
        if path == "/feeds/search":
            return {
                "feeds": [
                    {
                        "modelType": "note",
                        "id": NOTE,
                        "xsecToken": "public-note-locator",
                        "noteCard": {"displayTitle": "找软件开发"},
                    },
                    {"modelType": "hot_query", "id": "bad"},
                ]
            }
        assert body["load_all_comments"] is False
        return {
            "data": {
                "note": {"noteId": NOTE, "desc": RAW, "title": "找软件开发", "time": 1794614400000}
            }
        }

    monkeypatch.setattr(xiaohongshu, "request", request)
    rows = xiaohongshu.search_notes({"query": "软件开发"}, None)
    assert len(rows) == 1 and rows[0]["url"].endswith(NOTE)
    detail = xiaohongshu.read_note(rows[0], None)
    assert detail["published_at"] == "2026-11-14" and detail["raw_content"] == RAW
    assert "token" not in detail["url"]
    with pytest.raises(ProviderError):
        xiaohongshu.read_note({"note_id": "https://127.0.0.1"}, None)


def test_challenge_is_not_empty_and_write_endpoints_forbidden(monkeypatch):
    real = httpx.Client

    def handler(req):
        return httpx.Response(500, json={"code": "SEARCH_FAILED", "details": "验证码 required"})

    monkeypatch.setattr(
        xiaohongshu.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    cfg = SimpleNamespace(xiaohongshu_url="http://connector", xiaohongshu_token="")
    with pytest.raises(ProviderError) as e:
        xiaohongshu.request(cfg, "POST", "/feeds/search", {})
    assert e.value.code == "xhs_verification_required" and e.value.action_required
    with pytest.raises(ProviderError) as e:
        xiaohongshu.request(cfg, "POST", "/publish", {})
    assert e.value.code == "xhs_operation_not_allowed"


def test_search_to_terminal_feed_is_deduplicated_and_pushed_once(client, database, monkeypatch):
    r = client.post(
        "/api/v1/rules",
        json={"name": "social", "query": "找软件开发", "provider": "xiaohongshu", "enabled": True},
    ).json()
    with database.begin() as db:
        rule = db.get(Rule, r["id"])
        assert rule.source_type == "social_demand"
        task = service.start_rule(db, rule, "search-1")
        tid = task.id
    public, customer, social = [], [], []
    service.dispatch_pending(public.append, customer.append, social.append)
    assert social == [tid] and not public and not customer
    payload = {
        "note_id": NOTE,
        "note_token": "public-note-locator",
        "url": f"https://www.xiaohongshu.com/explore/{NOTE}",
        "title": "找软件开发",
        "raw_content": "",
        "published_at": None,
        "content_kind": "pending_note",
    }
    token, *_ = service.claim(tid)
    service.finish(tid, token, results=[payload, payload])
    with database() as db:
        tasks = db.scalars(select(Task).where(Task.parent_id == tid)).all()
        assert len(tasks) == 1
        ingest_id = tasks[0].id
    monkeypatch.setattr(
        xiaohongshu,
        "read_note",
        lambda p, c: {
            "title": "找软件开发",
            "raw_content": RAW,
            "published_at": today(),
            "content_kind": "platform_note",
        },
    )
    service.execute(ingest_id)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Item)) == 1
        assert "note_token" not in db.get(Task, ingest_id).payload
        assert db.scalar(select(Item)).information_kind == "demand"
    assert client.get("/api/v1/display/feed?after=0").json()["items"] == []
    from scout.ai_review import tick as review_tick
    from scout.config import Settings
    review_tick(Settings(_env_file=None, deepseek_api_key="test-key"), database,
                reviewer=lambda *args: {"decision": "buyer_demand", "reason": "买方需求", "evidence": RAW})
    assert (
        client.get("/api/v1/display/feed?after=0").json()["items"][0]["source_type"]
        == "social_demand"
    )
    snapshot = client.get("/api/v1/display/snapshot").json()
    assert snapshot["pending_count"] == 1 and snapshot["items"][0]["fragments"]
    assert snapshot["collectors"][0]["last_result_at"] is not None
    assert snapshot["collectors"][0]["last_opportunity_at"] is not None
    assert snapshot["collectors"][0]["search_engine"] == "xiaohongshu"
    # A repeat search must not enqueue another detail read, even before animation finishes.
    with database.begin() as db:
        t = service.start_rule(db, db.get(Rule, r["id"]), "search-2")
        tid2 = t.id
    token, *_ = service.claim(tid2)
    service.finish(tid2, token, results=[payload])
    with database() as db:
        assert not db.scalar(select(Task).where(Task.parent_id == tid2))
    from scout.dingtalk import tick

    class Send:
        def authenticate(self):
            pass

        def send(self, *args):
            return "social-test-message"

    with database.begin() as db:
        db.add(DeliveryGate(id="dingtalk"))
    cfg = SimpleNamespace(
        dingtalk_group_name="test-group",
        dingtalk_enabled=True,
        dingtalk_app_key="x",
        dingtalk_app_secret="x",
        dingtalk_robot_code="x",
        dingtalk_conversation_id="x",
    )
    assert tick(cfg, Send(), database) == "accepted"
    assert tick(cfg, Send(), database) == "waiting_claim"
    item = client.get("/api/v1/items").json()[0]
    assert item["business_status"] == "waiting_claim" and item["source_name"] == "小红书"


def test_login_resume_is_owner_or_admin_and_requeues_account_tasks(
    client, database, monkeypatch
):
    acc = client.post(
        "/api/v1/xiaohongshu/accounts",
        json={"name": "账号A", "url": "http://connector-a", "query": "找开发"},
    ).json()
    aid, rid = acc["id"], acc["rule"]["id"]
    admin_headers = dict(client.headers)
    with database.begin() as db:
        task = service.start_rule(db, db.get(Rule, rid), "auth-test")
        tid = task.id
    token, *_ = service.claim(tid)
    service.finish(tid, token, error=ProviderError("xhs_login_required", True))
    monkeypatch.setattr(xiaohongshu, "login_status", lambda c: {"is_logged_in": True})
    # 展示令牌没有用户身份，不能操作账号
    assert (
        client.post(
            f"/api/v1/xiaohongshu/accounts/{aid}/login/status",
            headers={"Authorization": "Bearer test-display"},
        ).status_code
        == 403
    )
    # 非建立者的普通成员只能看，不能操作
    client.post(
        "/api/v1/users",
        json={"username": "mike", "password": "mike12345", "role": "member"},
    )
    other = client.post(
        "/api/v1/auth/login", json={"username": "mike", "password": "mike12345"}
    ).json()["access_token"]
    assert (
        client.post(
            f"/api/v1/xiaohongshu/accounts/{aid}/login/status",
            headers={"Authorization": f"Bearer {other}"},
        ).status_code
        == 403
    )
    # 建立者操作成功，登录恢复后该账号等待中的任务重新排队
    assert client.post(
        f"/api/v1/xiaohongshu/accounts/{aid}/login/status", headers=admin_headers
    ).json()["is_logged_in"]
    with database() as db:
        assert db.get(Task, tid).status == "queued"


def test_one_login_failure_blocks_other_social_reads_without_blocking_public(
    client, database, monkeypatch
):
    r = client.post(
        "/api/v1/rules",
        json={"name": "social", "query": "找开发", "provider": "xiaohongshu", "enabled": True},
    ).json()
    with database.begin() as db:
        first = service.start_rule(db, db.get(Rule, r["id"]), "first-login")
        fid = first.id
        second = service.enqueue(
            db,
            kind="ingest",
            payload={
                "provider": "xiaohongshu",
                "source_type": "social_demand",
                "note_id": NOTE,
                "note_token": "locator",
            },
            key="next-detail",
            rule=db.get(Rule, r["id"]),
        )
        sid = second.id
        public = service.enqueue(
            db,
            kind="search",
            payload={"provider": "demo", "query": "软件需求"},
            key="public-independent",
        )
        pid = public.id
    token, *_ = service.claim(fid)
    service.finish(fid, token, error=ProviderError("xhs_verification_required", True))

    def no_request(*args, **kwargs):
        raise AssertionError("must not visit more notes after account is blocked")

    monkeypatch.setattr(xiaohongshu, "read_note", no_request)
    service.execute(sid)
    service.execute(pid)
    with database() as db:
        assert db.get(Task, sid).status == "action_required"
        assert db.get(Task, sid).error_code == "xhs_verification_required"
        assert db.get(Task, pid).status == "succeeded"


def test_social_supply_and_hashtags_are_not_purchase_demand():
    cases = [
        ("ERP定制开发", "需要ERP系统？专注企业ERP高端定制开发，免费获取开发报价"),
        ("寻找核心团队", "正在寻找核心后端工程师，具备软件系统经验"),
        ("海外软件案例参考", "想开发软件就找我们"),
        ("找软件开发公司！先要看这个", "找软件公司别先看规模，先看这一样 #软件开发[话题]#"),
        ("APP定制满意再付款", "想外包做软件的客户看过来，自有全职技术团队，为您提供方案"),
        ("软件公司怎么选择", "想咨询开发系统，主营业务为小程序开发，欢迎评论私信"),
        ("找开发想转AI的小伙伴", "我们团队需要你的加入，要求有软件经验，参与系统搭建"),
        ("AI智能体开发招人", "想找一份工作，公司有带教，岗位需要参加岗前实训"),
        ("客户上门沟通AI开发需求", "#软件开发公司[话题]# #小程序开发[话题]#"),
        ("接一些 AI Agent定制开发", "如果你有想用AI实现的业务需求，欢迎私信聊聊"),
        ("App开发全流程（收藏版）", "想做软件需要系统规划，整理流程图给大家"),
        ("开发智能体需要注意什么？", "需要增加系统的校验，分享开发经验"),
        ("软件需求交流", "#软件开发[话题]#"),
    ]
    for title, body in cases:
        assert describe_social_demand(title, body)["information_kind"] == "bulletin"
    assert (
        describe_social_demand("求推荐开发团队", "我们工厂需要升级ERP系统，想找软件公司沟通需求")[
            "information_kind"
        ]
        == "demand"
    )


def test_textless_note_does_not_block_next_search(database):
    with database.begin() as db:
        rule = Rule(
            name="social",
            query="找开发团队",
            provider="xiaohongshu",
            source_type="social_demand",
            enabled=True,
            next_run_at=0,
        )
        db.add(rule)
        db.flush()
        task = service.enqueue(
            db,
            kind="ingest",
            key="textless",
            payload={"provider": "xiaohongshu", "source_type": "social_demand"},
            rule=rule,
        )
        tid, rid = task.id, rule.id
    token, *_ = service.claim(tid)
    service.finish(tid, token, error=ProviderError("empty_content"))
    with database() as db:
        assert db.get(Task, tid).status == "failed"
        assert db.get(Rule, rid).next_run_at == 0
    service.schedule_due()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.kind == "search")) == 1
