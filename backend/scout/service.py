import hashlib
import re
import time

from sqlalchemy import func, select
from sqlalchemy import text as sql_text

from scout.config import settings
from scout.db import Session
from scout.models import Attempt, Document, Event, Item, Outbox, RemovedEvidence, Rule, Task, uid
from scout.providers import ProviderError, canonical_url, clean_text, search
from scout.quality import describe


def emit(db, task, kind, **data):
    db.add(Event(task_id=task.id, kind=kind, is_demo=task.is_demo, data=data))


def enqueue(db, *, kind, payload, key, rule=None, parent=None):
    existing = db.scalar(select(Task).where(Task.idempotency_key == key))
    if existing:
        return existing
    task = Task(
        kind=kind,
        payload=payload,
        idempotency_key=key,
        rule_id=rule.id if rule else (parent.rule_id if parent else None),
        parent_id=parent.id if parent else None,
        config_version=rule.version if rule else (parent.config_version if parent else 1),
        is_demo=payload.get("provider") == "demo",
        attempt_limit=settings().max_attempts,
    )
    db.add(task)
    db.flush()
    db.add(Outbox(task_id=task.id))
    emit(db, task, "task.queued", stage=kind)
    return task


def start_rule(db, rule, key):
    queries = [line.strip() for line in rule.query.splitlines() if line.strip()]
    rounds = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.rule_id == rule.id, Task.kind == "search")
        )
        or 0
    )
    # Explore distinct geographic scopes before revisiting the original query.
    scopes = [
        "",
        "上海",
        "江苏",
        "浙江",
        "广东",
        "山东",
        "北京",
        "四川",
        "湖北",
        "陕西",
        "福建",
        "安徽",
        "河南",
        "湖南",
        "河北",
        "重庆",
        "天津",
        "江西",
        "山西",
        "辽宁",
        "云南",
        "广西",
        "贵州",
        "内蒙古",
        "黑龙江",
        "吉林",
        "甘肃",
        "宁夏",
        "新疆",
        "海南",
        "青海",
        "西藏",
    ]
    scope = scopes[(rounds // len(queries)) % len(scopes)] if rule.interval_seconds == 0 else ""
    query = " ".join(part for part in (queries[rounds % len(queries)], scope) if part)
    return enqueue(
        db,
        kind="search",
        payload={
            "query": query,
            "provider": rule.provider,
            "max_results": rule.max_results,
            "page": rounds // (len(queries) * len(scopes)) + 1 if rule.provider == "searxng" else 1,
        },
        key=key,
        rule=rule,
    )


def claim(task_id):
    now = time.time()
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task or task.status not in ("queued", "retry_wait") or task.available_at > now:
            return None
        task.status = "running"
        task.attempts += 1
        task.lease_token = uid()
        task.lease_until = now + settings().lease_seconds
        task.updated_at = now
        db.add(Attempt(task_id=task.id, number=task.attempts))
        emit(db, task, "task.running", stage=task.kind)
        return task.lease_token, task.kind, task.payload


def save_item(db, task):
    p = task.payload
    url = canonical_url(p["url"])
    existing = db.scalar(select(Item).where(Item.url == url, Item.is_demo == task.is_demo).limit(1))
    if existing:
        emit(db, task, "item.duplicate", item_id=existing.id)
        return {"item_id": existing.id, "duplicate": True}
    raw = p["raw_content"]
    text = clean_text(raw)
    if not text:
        raise ProviderError("empty_content")
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    removed = db.scalar(select(RemovedEvidence).where(
        (RemovedEvidence.url_hash == hashlib.sha256(url.encode()).hexdigest()) |
        (RemovedEvidence.content_hash == fingerprint)).limit(1)) if not task.is_demo else None
    if removed:
        from scout.purge_bulletins import discarded_payload

        task.payload = discarded_payload(p.get("provider"), "removed_information")
        emit(db, task, "item.discarded", reason="removed_information")
        return {"discarded": True, "reason": "removed_information"}
    quality = describe(p["title"], raw, p.get("published_at"))
    if not task.is_demo and quality["information_kind"] == "bulletin":
        from scout.purge_bulletins import discarded_payload

        task.payload = discarded_payload(p.get("provider"))
        emit(db, task, "item.discarded", reason="not_opportunity")
        return {"discarded": True, "reason": "not_opportunity"}
    if task.is_demo and quality["quality_reason"] == "unverified_date":
        quality.update(quality_status="active", quality_reason=None)
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    # Serialize identical content across concurrent PostgreSQL workers.
    if db.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(f"{task.is_demo}|{fingerprint}".encode()).digest()[:8], "big", signed=True)
        db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    duplicate = db.scalar(select(Item).join(Document, Item.document_id == Document.id).where(
        Document.content_hash == fingerprint, Item.is_demo == task.is_demo).limit(1))
    if duplicate:
        emit(db, task, "item.duplicate", item_id=duplicate.id)
        return {"item_id": duplicate.id, "duplicate": True}
    identity = hashlib.sha256(f"{task.is_demo}|{url}".encode()).hexdigest()
    # Savepoint handles concurrent workers seeing the same URL/content.
    from sqlalchemy.exc import IntegrityError

    try:
        with db.begin_nested():
            doc = Document(
                identity=identity,
                url=url,
                title=p["title"],
                raw_content=raw,
                content_kind=p["content_kind"],
                content_hash=fingerprint,
                provider=p["provider"],
                published_at=p.get("published_at"),
                is_demo=task.is_demo,
            )
            db.add(doc)
            db.flush()
            contacts = [
                {"type": "email", "value": v}
                for v in sorted(
                    set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
                )[:20]
            ]
            contacts += [
                {"type": "phone", "value": v}
                for v in sorted(set(re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", text)))[:20]
            ]
            item = Item(
                document_id=doc.id,
                title=p["title"],
                url=url,
                text=quality["text"],
                fragments=quality["fragments"],
                category=quality["category"],
                information_kind=quality["information_kind"],
                quality_status=quality["quality_status"],
                quality_reason=quality["quality_reason"],
                region=quality["region"],
                region_evidence=quality["region_evidence"],
                published_at=quality["published_at"],
                contacts=contacts,
                is_demo=task.is_demo,
            )
            db.add(item)
            db.flush()
    except IntegrityError:
        doc = db.scalar(select(Document).where(Document.identity == identity))
        if doc is None:
            raise
        item = db.scalar(select(Item).where(Item.document_id == doc.id))
        emit(db, task, "item.duplicate", item_id=item.id)
        return {"item_id": item.id, "duplicate": True}
    emit(db, task, "item.created" if item.quality_status == "active" else "item.filtered", item_id=item.id)
    return {"item_id": item.id, "duplicate": False}


def finish(task_id, token, results=None, error=None):
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task or task.status != "running" or task.lease_token != token:
            return  # Fencing: a timed-out worker cannot overwrite a later attempt.
        if not error:
            try:
                if task.kind == "search":
                    for i, result in enumerate(results):
                        enqueue(
                            db,
                            kind="ingest",
                            payload={**result, "provider": task.payload["provider"]},
                            key=f"child:{task.id}:{i}",
                            parent=task,
                        )
                    task.result = {"discovered": len(results)}
                else:
                    task.result = save_item(db, task)
            except ProviderError as exc:
                error = exc
        if error:
            task.error_code = error.code
            task.status = (
                "action_required"
                if error.action_required
                else ("retry_wait" if task.attempts < task.attempt_limit else "failed")
            )
            task.available_at = time.time() + min(300, 5 * 2 ** min(task.attempts, 6))
        else:
            task.status = "succeeded"
            task.error_code = None
        task.lease_until = None
        task.lease_token = None
        task.updated_at = time.time()
        attempt = db.scalar(
            select(Attempt).where(Attempt.task_id == task.id, Attempt.number == task.attempts)
        )
        attempt.outcome = task.status
        attempt.ended_at = time.time()
        emit(db, task, f"task.{task.status}", error_code=task.error_code)


def execute(task_id):
    claimed = claim(task_id)
    if not claimed:
        return
    token, kind, payload = claimed
    try:
        results = search(payload, settings()) if kind == "search" else None
        finish(task_id, token, results=results)
    except ProviderError as exc:
        finish(task_id, token, error=exc)
    except Exception:
        # Do not log payloads, raw responses or credentials. The lease recovers DB failures.
        finish(task_id, token, error=ProviderError("worker_error"))


def schedule_due():
    with Session.begin() as db:
        rules = db.scalars(
            select(Rule)
            .where(Rule.enabled.is_(True), Rule.next_run_at <= time.time())
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for rule in rules:
            # No overlapping search for one rule, including an authorization wait.
            active = db.scalar(
                select(Task.id).where(
                    Task.rule_id == rule.id,
                    Task.status.in_(["queued", "running", "retry_wait"]),
                )
            )
            blocked = db.scalar(
                select(Task.id).where(
                    Task.rule_id == rule.id, Task.kind == "search", Task.status == "action_required"
                )
            )
            if blocked:
                continue
            if active:
                continue
            if not active:
                start_rule(db, rule, f"schedule:{rule.id}:{rule.version}:{rule.next_run_at}")
            rule.next_run_at = time.time() + max(3, rule.interval_seconds)


def recover_expired():
    with Session.begin() as db:
        tasks = db.scalars(
            select(Task)
            .where(Task.status == "running", Task.lease_until < time.time())
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for task in tasks:
            task.status = "retry_wait" if task.attempts < task.attempt_limit else "failed"
            task.error_code = "worker_lease_expired"
            task.lease_token = None
            task.lease_until = None
            task.available_at = time.time()
            task.updated_at = time.time()
            attempt = db.scalar(
                select(Attempt).where(Attempt.task_id == task.id, Attempt.number == task.attempts)
            )
            attempt.outcome = "lease_expired"
            attempt.ended_at = time.time()
            emit(db, task, f"task.{task.status}", error_code=task.error_code)


def dispatch_pending(publish):
    with Session.begin() as db:
        rows = db.scalars(
            select(Outbox)
            .join(Task)
            .where(
                Task.status.in_(["queued", "retry_wait"]),
                Task.available_at <= time.time(),
                Outbox.next_publish_at <= time.time(),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for row in rows:
            publish(row.task_id)  # Crash after publish is safe: duplicate execution is fenced.
            row.publishes += 1
            row.next_publish_at = time.time() + 30  # Reconcile lost broker messages until claimed.
