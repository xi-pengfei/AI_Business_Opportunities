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


def test_demo_separation_and_display_redaction(client, database):
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
    assert "text" not in redacted["items"][0]
    assert "contacts" not in redacted["items"][0]
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
    assert "url" not in public["items"][0]
    assert "contacts" not in public["items"][0]
    assert "私有" not in str(public)
    assert client.get(path + "&offset=50").json()["items"] == []
    assert client.get("/api/v1/display/items?start=2&end=1").status_code == 422
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
