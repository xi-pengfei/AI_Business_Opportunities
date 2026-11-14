import time

import pytest
from sqlalchemy import func, select

from scout import service
from scout.models import Attempt, Document, Event, Item, Outbox, Rule, Task
from scout.providers import ProviderError, canonical_url, clean_text


def make_task(database, provider="demo", key="test"):
    with database.begin() as db:
        rule = Rule(name="供应商", query="供应商对账", provider=provider)
        db.add(rule)
        db.flush()
        return service.start_rule(db, rule, key).id


def drain(database, task_id):
    service.execute(task_id)
    with database() as db:
        children = list(db.scalars(select(Task.id).where(Task.parent_id == task_id)))
    for child in children:
        service.execute(child)
    return children


def test_demo_pipeline_and_duplicate_delivery(database):
    task_id = make_task(database)
    children = drain(database, task_id)
    service.execute(task_id)
    service.execute(children[0])
    second = make_task(database, key="second")
    drain(database, second)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Item)) == 1
        assert db.scalar(select(func.count()).select_from(Document)) == 1
        assert (
            db.scalar(select(func.count()).select_from(Event).where(Event.kind == "item.created"))
            == 1
        )
        assert db.get(Task, task_id).attempts == 1
        assert db.get(Task, children[0]).status == "succeeded"
        assert db.scalar(select(Item)).contacts == []


def test_missing_key_does_not_block_other_tasks(database):
    missing = make_task(database, "tavily", "missing")
    service.execute(missing)
    drain(database, make_task(database, key="good"))
    with database() as db:
        assert db.get(Task, missing).status == "action_required"
        assert db.get(Task, missing).error_code == "search_key_missing"
        assert db.scalar(select(func.count()).select_from(Item)) == 1


def test_expired_worker_fenced_and_recovered(database):
    task_id = make_task(database)
    old_token, _, _ = service.claim(task_id)
    with database.begin() as db:
        db.get(Task, task_id).lease_until = time.time() - 1
    service.recover_expired()
    new_token, _, _ = service.claim(task_id)
    service.finish(task_id, old_token, results=[])
    with database() as db:
        assert db.get(Task, task_id).status == "running"
        assert db.get(Task, task_id).lease_token == new_token
    service.finish(task_id, new_token, results=[])
    with database() as db:
        assert db.get(Task, task_id).status == "succeeded"
        assert db.scalar(select(Attempt).where(Attempt.number == 1)).outcome == "lease_expired"


def test_retry_limit_and_failure_isolation(database, monkeypatch):
    task_id = make_task(database)

    def fail(*args):
        raise ProviderError("search_rate_limited")

    monkeypatch.setattr(service, "search", fail)
    for _ in range(3):
        service.execute(task_id)
        with database.begin() as db:
            db.get(Task, task_id).available_at = time.time() - 1
    with database() as db:
        assert db.get(Task, task_id).status == "failed"
        assert db.get(Task, task_id).attempts == 3


def test_outbox_survives_broker_failure_and_republishes(database):
    task_id = make_task(database)

    def unavailable(task):
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        service.dispatch_pending(unavailable)
    with database() as db:
        assert db.get(Outbox, task_id).publishes == 0
        assert db.get(Task, task_id).status == "queued"
    messages = []
    service.dispatch_pending(messages.append)
    with database.begin() as db:
        db.get(Outbox, task_id).next_publish_at = time.time() - 1
    service.dispatch_pending(messages.append)
    assert messages == [task_id, task_id]


def test_schedule_no_overlap_and_disabled_rule(database):
    task_id = make_task(database)
    with database.begin() as db:
        rule = db.get(Rule, db.get(Task, task_id).rule_id)
        rule.enabled = True
        rule.next_run_at = 0
    service.schedule_due()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
    drain(database, task_id)
    with database.begin() as db:
        rule = db.get(Rule, db.get(Task, task_id).rule_id)
        rule.enabled = False
        rule.next_run_at = 0
    service.schedule_due()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.kind == "search")) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/a",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://localhost/",
        "https://user:pass@example.com",
    ],
)
def test_unsafe_evidence_urls_rejected(url):
    with pytest.raises(ProviderError):
        canonical_url(url)


def test_content_is_untrusted_text():
    assert clean_text("<script>alert(1)</script><p>订单 <b>系统</b></p>") == "订单 系统"
    assert canonical_url("https://EXAMPLE.com:443/a#x") == "https://example.com/a"


def test_bad_source_does_not_cancel_other_results(database, monkeypatch):
    task_id = make_task(database)
    monkeypatch.setattr(
        service,
        "search",
        lambda *_: [
            {
                "title": "有效来源",
                "url": "https://example.com/good",
                "raw_content": "有效需求",
                "content_kind": "demo",
            },
            {
                "title": "无效来源",
                "url": "file:///etc/passwd",
                "raw_content": "不应入库",
                "content_kind": "demo",
            },
        ],
    )
    children = drain(database, task_id)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Item)) == 1
        assert {db.get(Task, c).status for c in children} == {"succeeded", "retry_wait"}


def test_display_cumulative_dedupe_and_window_baseline(database):
    from scout.display import chart_facts

    drain(database, make_task(database, key="chart-one"))
    drain(database, make_task(database, key="chart-two"))
    with database() as db:
        current = chart_facts(db, True, int(time.time() // 60) * 60 - 29 * 60)
        assert current["collection_history"][-1][1:] == [2, 1, 0]
        assert current["source_counts"] == {"demo": 1}
        future = chart_facts(db, True, time.time() + 60)
        assert all(row[1:] == [2, 1, 0] for row in future["collection_history"])
        live = chart_facts(db, False, time.time() - 60)
        assert all(row[1:] == [0, 0, 0] for row in live["collection_history"])
        assert live["source_counts"] == {}


def test_display_queue_counts_retry(database):
    from scout.display import chart_facts

    task_id = make_task(database)
    start = int(time.time() // 60) * 60 - 29 * 60
    with database() as db:
        assert chart_facts(db, True, start)["collection_history"][-1][3] == 1
    token, _, _ = service.claim(task_id)
    service.finish(task_id, token, error=ProviderError("temporary"))
    with database() as db:
        assert chart_facts(db, True, start)["collection_history"][-1][3] == 1


def test_continuous_rotates_queries_waits_for_ingest_and_stops(database):
    with database.begin() as db:
        rule = Rule(
            name="continuous",
            query="ERP\nMES",
            provider="demo",
            enabled=True,
            interval_seconds=0,
            max_results=20,
            next_run_at=0,
        )
        db.add(rule)
        db.flush()
        rid = rule.id
    service.schedule_due()
    with database() as db:
        first = db.scalar(select(Task).where(Task.kind == "search"))
        tid = first.id
        assert first.payload["query"] == "ERP"
    service.execute(tid)
    with database.begin() as db:
        db.get(Rule, rid).next_run_at = time.time() - 1
    service.schedule_due()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.kind == "search")) == 1
        child = db.scalar(select(Task.id).where(Task.parent_id == tid))
    service.execute(child)
    service.schedule_due()
    with database() as db:
        searches = list(
            db.scalars(select(Task).where(Task.kind == "search").order_by(Task.created_at))
        )
        assert [t.payload["query"] for t in searches] == ["ERP", "MES"]
    drain(database, searches[-1].id)
    with database.begin() as db:
        db.get(Rule, rid).enabled = False
        db.get(Rule, rid).next_run_at = time.time() - 1
    service.schedule_due()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.kind == "search")) == 2
