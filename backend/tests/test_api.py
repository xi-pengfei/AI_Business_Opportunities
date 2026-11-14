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
