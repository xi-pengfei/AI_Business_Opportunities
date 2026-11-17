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


def start_rule(db, rule, key, scheduled=False):
    queries = [line.strip() for line in rule.query.splitlines() if line.strip()]
    rounds = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.rule_id == rule.id, Task.kind == "search")
        )
        or 0
    )
    lane = None
    if rule.provider == "searxng" and rule.interval_seconds == 0:
        from scout.search_plan import choose
        engines = [e.strip() for e in settings().searxng_engines.split(",") if e.strip()]
        lane = choose(db,rule,engines,force=not scheduled)
        if lane is None:
            return None
    query = lane.query if lane else queries[rounds % len(queries)]
    customer_snapshot = None
    if rule.customer_id:
        from scout.models import Customer
        customer = db.get(Customer, rule.customer_id)
        if customer:
            customer_snapshot = {"name": customer.name, "aliases": customer.aliases}
    task = enqueue(
        db,
        kind="search",
        payload={
            "query": query,
            "provider": rule.provider,
            "source_type": rule.source_type or "public_tender",
            **({"customer_id": rule.customer_id} if rule.customer_id else {}),
            **({"customer_snapshot": customer_snapshot} if customer_snapshot else {}),
            **({"xhs_account_id": rule.xhs_account_id} if rule.xhs_account_id else {}),
            "max_results": rule.max_results,
            "page": lane.page if lane else 1,
            **({"engine":lane.engine,"search_cursor_id":lane.id} if lane else {}),
        },
        key=key,
        rule=rule,
    )

    if lane or rule.provider == "xiaohongshu":
        task.attempt_limit = 1  # Cursor cooldown retries this source without blocking others.
    return task


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
    if p.get("source_type") == "customer_watch":
        from scout.customers import save_signal
        return save_signal(db, task)
    url = canonical_url(p["url"])
    raw = p["raw_content"]
    text = clean_text(raw)
    if not text:
        raise ProviderError("empty_content")
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    existing = db.scalar(select(Item).join(Document, Item.document_id == Document.id).where(
        Item.url == url, Item.is_demo == task.is_demo, Document.content_hash == fingerprint,
        Item.information_kind.in_(("opportunity", "demand"))).limit(1))
    if existing:
        emit(db, task, "item.duplicate", item_id=existing.id)
        return {"item_id": existing.id, "duplicate": True}
    removed = db.scalar(select(RemovedEvidence).where(
        (RemovedEvidence.url_hash == hashlib.sha256(url.encode()).hexdigest()) |
        (RemovedEvidence.content_hash == fingerprint)).limit(1)) if not task.is_demo and p.get("source_type", "public_tender") == "public_tender" else None
    if removed:
        from scout.purge_bulletins import discarded_payload

        task.payload = discarded_payload(p.get("provider"), "removed_information")
        emit(db, task, "item.discarded", reason="removed_information")
        return {"discarded": True, "reason": "removed_information"}
    from scout.policies import describe_public_tender, describe_social_demand

    if not task.is_demo and p.get("source_type", "public_tender") not in ("public_tender", "social_demand"):
        raise ProviderError("source_policy_not_connected", True)
    policy = describe_social_demand if p.get("source_type") == "social_demand" else describe_public_tender
    quality = (describe if task.is_demo else policy)(p["title"], raw, p.get("published_at"))
    if not task.is_demo and p.get("source_type") == "social_demand" and quality["quality_status"] == "active":
        # AI sees every fresh social candidate, including ones regex would reject.
        quality.update(information_kind="demand", quality_status="review_pending", quality_reason="ai_review_required")
    if not task.is_demo and quality["information_kind"] == "bulletin":
        from scout.purge_bulletins import discarded_payload

        task.payload = {**discarded_payload(p.get("provider")), "source_type": p.get("source_type", "public_tender"), **({"note_id": p["note_id"]} if p.get("note_id") else {})}
        emit(db, task, "item.discarded", reason="not_opportunity")
        return {"discarded": True, "reason": "not_opportunity"}
    if not task.is_demo and quality["quality_status"] == "active" and quality["information_kind"] in ("opportunity", "demand"):
        quality.update(quality_status="review_pending", quality_reason="ai_review_required")
    if task.is_demo and quality["quality_reason"] == "unverified_date":
        quality.update(quality_status="active", quality_reason=None)
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    # Serialize identical content across concurrent PostgreSQL workers.
    if db.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(f"{task.is_demo}|{fingerprint}".encode()).digest()[:8], "big", signed=True)
        db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    duplicate = db.scalar(select(Item).join(Document, Item.document_id == Document.id).where(
        Document.content_hash == fingerprint, Item.is_demo == task.is_demo,
        Item.information_kind.in_(("opportunity", "demand"))).limit(1))
    if duplicate:
        duplicate.source_urls = list(dict.fromkeys([duplicate.url, *duplicate.source_urls, url]))
        emit(db, task, "item.duplicate", item_id=duplicate.id)
        return {"item_id": duplicate.id, "duplicate": True}
    identity = hashlib.sha256(f"{task.is_demo}|{url}|{fingerprint}".encode()).hexdigest()
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
                source_type=p.get("source_type", "public_tender"),
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


def finish(task_id, token, results=None, error=None, prepared=None):
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task or task.status != "running" or task.lease_token != token:
            return  # Fencing: a timed-out worker cannot overwrite a later attempt.
        if not error:
            try:
                if task.kind == "search":
                    for i, result in enumerate(results):
                        if task.payload.get("provider") == "xiaohongshu":
                            already = db.scalar(select(Task.id).where(Task.kind == "ingest",
                                Task.payload["note_id"].as_string() == result["note_id"],
                                Task.status.in_(("queued", "running", "retry_wait", "succeeded", "action_required"))).limit(1))
                            if already:
                                continue
                        enqueue(
                            db,
                            kind="ingest",
                            payload={**result, "provider": task.payload["provider"], "source_type": task.payload.get("source_type","public_tender"), **({"customer_id": task.payload["customer_id"], "customer_snapshot": task.payload.get("customer_snapshot")} if task.payload.get("customer_id") else {}), **({"xhs_account_id": task.payload["xhs_account_id"]} if task.payload.get("xhs_account_id") else {})},
                            key=f"child:{task.id}:{i}",
                            parent=task,
                        )
                    task.result = {"discovered": len(results), **getattr(results,"diagnostics",{})}
                else:
                    if prepared is not None:
                        task.payload = {**task.payload, **prepared}
                        task.payload = {k: v for k, v in task.payload.items() if k != "note_token"}
                    task.result = save_item(db, task)
            except ProviderError as exc:
                error = exc
        if task.kind == "search":
            from scout.search_plan import complete
            complete(db,task,results or [],error)
        if error:
            task.error_code = error.code
            if task.payload.get("provider") == "xiaohongshu" and error.code == "empty_content":
                task.attempt_limit = task.attempts  # Textless notes cannot improve through retries.
            if task.payload.get("provider") == "xiaohongshu" and error.code != "empty_content":
                # 登录/风控只冷却同账号的规则；无账号的遗留规则按全局配置处理。
                for rule in db.scalars(select(Rule).where(Rule.provider == "xiaohongshu")):
                    if rule.xhs_account_id == task.payload.get("xhs_account_id"):
                        rule.next_run_at = max(rule.next_run_at, time.time() + 600)
            task.status = (
                "action_required"
                if error.action_required
                else ("retry_wait" if task.attempts < task.attempt_limit else "failed")
            )
            task.available_at = time.time() + (600 if task.payload.get("provider") == "xiaohongshu" else min(300, 5 * 2 ** min(task.attempts, 6)))
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


def xhs_config(payload):
    """按任务载荷取该账号的连接器配置；无账号的遗留任务回落到全局 .env 配置。"""
    from types import SimpleNamespace
    account_id = payload.get("xhs_account_id")
    if not account_id:
        return settings()
    from scout.models import XhsAccount
    with Session() as db:
        account = db.get(XhsAccount, account_id)
    if account is None or not account.enabled:
        raise ProviderError("xhs_not_configured", True)
    base = settings()
    return SimpleNamespace(**{**base.model_dump(), "xiaohongshu_url": account.url, "xiaohongshu_token": account.token})


def execute(task_id):
    claimed = claim(task_id)
    if not claimed:
        return
    token, kind, payload = claimed
    try:
        if payload.get("provider") == "xiaohongshu":
            with Session() as db:
                blocked = db.scalar(select(Task.error_code).where(
                    Task.payload["provider"].as_string() == "xiaohongshu",
                    func.coalesce(Task.payload["xhs_account_id"].as_string(), "") == (payload.get("xhs_account_id") or ""),
                    Task.status == "action_required",
                    Task.error_code.in_(("xhs_login_required", "xhs_verification_required"))).limit(1))
            if blocked:
                raise ProviderError(blocked, True)
        config = xhs_config(payload) if payload.get("provider") == "xiaohongshu" else settings()
        results = search(payload, config) if kind == "search" else None
        prepared = None
        if kind == "ingest" and payload.get("provider") == "xiaohongshu" and payload.get("note_token"):
            from scout.xiaohongshu import read_note
            prepared = read_note(payload, config)
        finish(task_id, token, results=results, prepared=prepared)
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
                    (Task.rule_id.in_(select(Rule.id).where(Rule.provider == "xiaohongshu")) if rule.provider == "xiaohongshu" else (Task.rule_id == rule.id) & (Task.config_version == rule.version)), Task.status == "action_required"
                )
            )
            if blocked:
                continue
            if active:
                continue
            if not active:
                if start_rule(db, rule, f"schedule:{rule.id}:{rule.version}:{rule.next_run_at}", scheduled=True) is None:
                    continue
            rule.next_run_at = time.time() + max(60 if rule.provider == "xiaohongshu" else 3, rule.interval_seconds)


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


def dispatch_pending(publish, publish_customer=None, publish_social=None):
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
            task = db.get(Task, row.task_id)
            send = publish_customer if publish_customer and task.payload.get("source_type") == "customer_watch" else publish
            if publish_social and task.payload.get("source_type") == "social_demand":
                send = publish_social
            send(row.task_id)  # Crash after publish is safe: duplicate execution is fenced.
            row.publishes += 1
            row.next_publish_at = time.time() + 30  # Reconcile lost broker messages until claimed.
