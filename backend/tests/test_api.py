from sqlalchemy import select

from scout import service
from scout.models import Task


def test_validation_auth_and_manual_idempotency(client):
    assert client.get("/api/v1/rules", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert (
        client.get("/api/v1/rules", headers={"Authorization": "Bearer test-display"}).status_code
        == 403
    )
    assert client.post("/api/v1/rules", json={"name": " ", "query": "x"}).status_code == 422
    response = client.post(
        "/api/v1/rules", json={"name": "测试", "query": "ERP", "provider": "demo"}
    )
    assert response.status_code == 201
    rule = response.json()
    assert not rule["enabled"]
    a = client.post(f"/api/v1/rules/{rule['id']}/run", headers={"Idempotency-Key": "same"})
    b = client.post(f"/api/v1/rules/{rule['id']}/run", headers={"Idempotency-Key": "same"})
    assert a.status_code == 202
    assert a.json()["id"] == b.json()["id"]
    assert "payload" not in a.json()


def test_demo_separation_and_display_snapshot(client, database):
    rule = client.post(
        "/api/v1/rules", json={"name": "测试", "query": "ERP", "provider": "demo"}
    ).json()
    task = client.post(f"/api/v1/rules/{rule['id']}/run", headers={"Idempotency-Key": "run"}).json()
    service.execute(task["id"])
    with database() as db:
        child = db.scalar(select(Task.id).where(Task.parent_id == task["id"]))
    service.execute(child)
    assert client.get("/api/v1/items").json() == []
    assert len(client.get("/api/v1/items?demo=true").json()) == 1
    redacted = client.get(
        "/api/v1/display/snapshot?demo=true", headers={"Authorization": "Bearer test-display"}
    ).json()
    assert redacted["item_count"] == 1
    # 展示模式不再脱敏（item_record：所有调用方看到完整条目），demo 与正式库仍然互相隔离。
    assert "text" in redacted["items"][0]
    assert sum(r[1] for r in redacted["trend"]) == 1
    assert (
        client.get("/api/v1/items", headers={"Authorization": "Bearer test-display"}).status_code
        == 403
    )


def test_retry_only_after_failure(client):
    rule = client.post(
        "/api/v1/rules", json={"name": "真实", "query": "ERP", "provider": "tavily"}
    ).json()
    task = client.post(f"/api/v1/rules/{rule['id']}/run", headers={"Idempotency-Key": "run"}).json()
    assert client.post(f"/api/v1/tasks/{task['id']}/retry").status_code == 409
    service.execute(task["id"])
    assert client.post(f"/api/v1/tasks/{task['id']}/retry").status_code == 202
    assert (
        client.get(f"/api/v1/tasks/{task['id']}").json()["attempt_history"][0]["outcome"]
        == "action_required"
    )


def test_chart_days_dedupe_and_filtered_evidence_permissions(client, database, monkeypatch):
    from datetime import datetime

    from scout import api
    from scout.models import Document, Item

    midnight = datetime.fromisoformat("2026-11-14T00:00:00+08:00").timestamp()
    monkeypatch.setattr(api.time, "time", lambda: midnight + 120)
    with database.begin() as db:
        for i, (url, stamp, provider, demo) in enumerate([
            ("https://example.org/a", midnight - 1, "tavily", False),
            ("https://example.org/a", midnight + 1, "searxng", False),
            ("https://example.org/b", midnight, "searxng", False),
            ("https://example.org/c", midnight + 60, "searxng", False),
            ("https://example.org/d", midnight + 1, "demo", True),
        ]):
            doc = Document(id=str(i), identity=str(i), url=url, title="私有标题",
                           raw_content="私有内容", content_kind="search_excerpt",
                           content_hash=str(i), provider=provider, is_demo=demo)
            db.add(doc)
            db.flush()
            db.add(Item(document_id=doc.id, title="私有标题", url=url, text="私有内容",
                        contacts=[{"type": "email", "value": "private@example.org"}],
                        ai_review={"decision": "buyer_demand"},
                        created_at=stamp, is_demo=demo))
    snapshot = client.get("/api/v1/display/snapshot").json()
    assert len(snapshot["discovery_calendar"]) == 90
    assert snapshot["discovery_calendar"][-1]["count"] == 2
    assert snapshot["discovery_calendar"][-2]["count"] == 1
    assert sum(sum(r["sources"].values()) for r in snapshot["discovery_history"]) == 3
    path = f"/api/v1/display/items?start={midnight}&end={midnight + 60}&provider=searxng"
    result = client.get(path).json()
    assert result["total"] == 1
    assert result["items"][0]["url"] == "https://example.org/b"
    public = client.get(path, headers={"Authorization": "Bearer test-display"}).json()
    assert public["total"] == 1
    # 展示模式不再脱敏（eec8275）：展示令牌同样看到完整条目（标题、链接与正文）。
    assert public["items"][0]["url"] == "https://example.org/b"
    assert public["items"][0]["title"].startswith("私有")
    assert client.get(path + "&offset=50").json()["items"] == []
    assert client.get("/api/v1/display/items?start=2&end=1").status_code == 422
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_feed_cursor_and_map_exclude_archived_records(client, database):
    from scout.models import Document, Item

    with database.begin() as db:
        for key, archived in [("a", False), ("b", False), ("c", True)]:
            doc = Document(id=key, identity=key, url=f"https://example.org/{key}", title="湖北采购",
                           raw_content="建设系统", content_kind="search_excerpt", content_hash=key,
                           provider="searxng", is_demo=False)
            db.add(doc)
            db.flush()
            db.add(Item(id=key, document_id=key, title="湖北采购", url=doc.url, text="建设系统",
                        information_kind="opportunity", ai_review={"decision": "buyer_demand"}, created_at=100, is_demo=False, region="湖北", region_evidence="湖北采购",
                        quality_status="archived" if archived else "active"))
    feed = client.get("/api/v1/display/feed?after=100&after_id=a").json()
    assert [i["id"] for i in feed["items"]] == ["b"]
    assert feed["after_id"] == "b"
    assert client.get("/api/v1/display/feed?after=100&after_id=b").json()["items"] == []
    public = client.get("/api/v1/display/feed?after=0", headers={"Authorization": "Bearer test-display"}).json()
    # 展示模式不再脱敏（eec8275）：feed 同样返回完整条目。
    assert public["items"][0]["text"] == "建设系统"
    assert public["items"][0]["url"] == "https://example.org/a"
    assert len(client.get("/api/v1/items").json()) == 2
    assert client.get("/api/v1/display/items?start=0&end=101&region=湖北").json()["total"] == 2
    assert client.get("/api/v1/display/items?start=0&end=101&region=广东").json()["total"] == 0


def test_edit_network_rule_preserves_enabled_state_and_revisions(client, database):
    from scout.models import Rule
    r = client.post('/api/v1/rules', json={'name':'原名称','query':'ERP 采购公告','provider':'searxng','enabled':True}).json()
    edited = client.patch('/api/v1/rules/'+r['id'],json={'name':'MES 商机','query':'MES 招标公告\nMES 采购意向','provider':'searxng'}).json()
    assert edited['enabled'] is True
    assert edited['version'] == r['version']+1
    assert edited['query'].splitlines() == ['MES 招标公告','MES 采购意向']
    client.patch('/api/v1/rules/'+r['id'],json={'enabled':False})
    assert client.patch('/api/v1/rules/'+r['id'],json={'name':'停止后修改'}).json()['enabled'] is False
    assert client.patch('/api/v1/rules/'+r['id'],json={'query':'  '}).status_code == 422
    with database() as db:
        assert db.get(Rule,r['id']).query == edited['query']


def test_new_network_config_not_blocked_by_old_provider_auth_failure(client, database):
    from scout.models import Rule
    r = client.post('/api/v1/rules', json={'name':'缺密钥','query':'ERP 采购公告','provider':'tavily','enabled':True}).json()
    service.schedule_due()
    with database.begin() as db:
        old = db.scalar(select(Task).where(Task.rule_id==r['id']))
        old.status = 'action_required'
    client.patch('/api/v1/rules/'+r['id'],json={'provider':'searxng'})
    service.schedule_due()
    with database() as db:
        tasks = db.scalars(select(Task).where(Task.rule_id==r['id'])).all()
        assert len(tasks) == 2
        new = next(t for t in tasks if t.status=='queued')
        assert new.payload['provider'] == 'searxng'
        assert new.config_version == db.get(Rule,r['id']).version
