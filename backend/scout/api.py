import asyncio
import json
import secrets
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text

from scout.assignments import assignment_facts, pending_items
from scout.config import settings
from scout.db import Session
from scout.display import chart_facts, collector_status, discovery_facts, public_tasks, unique_items
from scout.models import (
    Attempt,
    Customer,
    CustomerSignal,
    Document,
    Event,
    Item,
    Outbox,
    Rule,
    Task,
)
from scout.service import emit, start_rule

app = FastAPI(title="AI商机智能体", version="0.1.0")


def role(authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ")
    if token and settings().admin_token and secrets.compare_digest(token, settings().admin_token):
        return "admin"
    if (
        token
        and settings().display_token
        and secrets.compare_digest(token, settings().display_token)
    ):
        return "display"
    raise HTTPException(401, "需要有效的访问令牌")


def admin(current=Depends(role)):
    if current != "admin":
        raise HTTPException(403, "此操作需要管理员权限")


def record(row, exclude=()):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}


def task_record(row):
    return record(row, ("payload", "lease_token", "idempotency_key"))


class RuleInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=500)
    provider: Literal["searxng", "tavily", "demo", "xiaohongshu"] = "searxng"
    interval_seconds: int = Field(default=0, ge=0, le=2592000)
    max_results: int = Field(default=20, ge=1, le=20)
    enabled: bool = False

    @field_validator("name", "query")
    @classmethod
    def strip_text(cls, value):
        if not value.strip():
            raise ValueError("不能只包含空白")
        return value.strip()


class EnableInput(BaseModel):
    enabled: bool
    interval_seconds: int | None = Field(default=None, ge=0, le=2592000)
    max_results: int | None = Field(default=None, ge=1, le=20)
    query: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value):
        if value is not None and not value.strip():
            raise ValueError("关键词不能为空")
        return value


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        with Session() as db:
            db.execute(text("select 1"))
        return {"database": "ok"}
    except Exception:
        raise HTTPException(503, "数据库不可用") from None


@app.get("/api/v1/providers", dependencies=[Depends(admin)])
def providers():
    return {
        "searxng": {"configured": bool(settings().searxng_url)},
        "tavily": {"configured": bool(settings().tavily_api_key)},
        "demo": {"enabled": settings().allow_demo},
    }


@app.get("/api/v1/rules", dependencies=[Depends(admin)])
def rules():
    with Session() as db:
        return [
            record(r) for r in db.scalars(select(Rule).where(Rule.source_type.in_(("public_tender", "social_demand"))).order_by(Rule.created_at.desc()).limit(100))
        ]


@app.post("/api/v1/rules", status_code=201, dependencies=[Depends(admin)])
def create_rule(body: RuleInput):
    if body.provider == "demo" and not settings().allow_demo:
        raise HTTPException(422, "演示适配器未启用")
    with Session.begin() as db:
        rule = Rule(**body.model_dump(), source_type="social_demand" if body.provider == "xiaohongshu" else "public_tender")
        db.add(rule)
        db.flush()
        return record(rule)


@app.patch("/api/v1/rules/{rule_id}", dependencies=[Depends(admin)])
def enable_rule(rule_id: str, body: EnableInput):
    with Session.begin() as db:
        rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())
        if not rule:
            raise HTTPException(404, "规则不存在")
        rule.enabled = body.enabled
        for field in ("interval_seconds", "max_results", "query"):
            value = getattr(body, field)
            if value is not None:
                setattr(rule, field, value)
        rule.version += 1
        if body.enabled:
            rule.next_run_at = time.time()
        return record(rule)


@app.post("/api/v1/rules/{rule_id}/run", status_code=202, dependencies=[Depends(admin)])
def run_rule(rule_id: str, idempotency_key: Annotated[str, Header(min_length=1, max_length=100)]):
    with Session.begin() as db:
        rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())
        if not rule:
            raise HTTPException(404, "规则不存在")
        return task_record(start_rule(db, rule, f"manual:{rule_id}:{idempotency_key}"))


@app.get("/api/v1/tasks", dependencies=[Depends(admin)])
def tasks(demo: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with Session() as db:
        return [
            task_record(t)
            for t in db.scalars(
                select(Task)
                .where(Task.is_demo == demo)
                .order_by(Task.created_at.desc(), Task.id)
                .offset(offset)
                .limit(limit)
            )
        ]


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(admin)])
def task_detail(task_id: str):
    with Session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise HTTPException(404, "任务不存在")
        return {
            **task_record(task),
            "attempt_history": [
                record(a)
                for a in db.scalars(
                    select(Attempt).where(Attempt.task_id == task_id).order_by(Attempt.number)
                )
            ],
        }


@app.post("/api/v1/tasks/{task_id}/retry", status_code=202, dependencies=[Depends(admin)])
def retry_task(task_id: str):
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            raise HTTPException(404, "任务不存在")
        if task.status not in ("action_required", "failed"):
            raise HTTPException(409, "仅待配置或失败任务可手动重试")
        task.status = "queued"
        task.error_code = None
        task.available_at = time.time()
        task.updated_at = time.time()
        task.attempt_limit = task.attempts + settings().max_attempts
        db.get(Outbox, task_id).next_publish_at = time.time()
        emit(db, task, "task.queued", manual_retry=True)
        return task_record(task)


@app.get("/api/v1/items", dependencies=[Depends(admin)])
def items(demo: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
          status: Literal["active", "archived"] = "active"):

    with Session() as db:
        return [
            record(i)
            for i in db.scalars(
                (unique_items(demo) if status == "active" else
                 select(Item).where(Item.is_demo == demo, Item.quality_status == "archived"))
                .order_by(Item.created_at.desc(), Item.id)
                .offset(offset)
                .limit(limit)
            )
        ]


@app.get("/api/v1/items/{item_id}", dependencies=[Depends(admin)])
def item_detail(item_id: str):
    with Session() as db:
        item = db.get(Item, item_id)
        if not item:
            raise HTTPException(404, "信息不存在")
        return {**record(item), "evidence": record(db.get(Document, item.document_id))}


@app.get("/api/v1/display/items")
def display_items(
    start: float = Query(ge=0, allow_inf_nan=False),
    end: float = Query(ge=0, allow_inf_nan=False),
    provider: str | None = Query(default=None, max_length=80),
    region: str | None = Query(default=None, max_length=20),
    offset: int = Query(0, ge=0),
    demo: bool = False,
    current=Depends(role),
):
    if end <= start or end - start > 86400 * 90:
        raise HTTPException(422, "请选择90天以内的有效时间范围")
    with Session() as db:
        query = unique_items(demo).where(Item.created_at >= start, Item.created_at < end)
        if region:
            query = query.where(Item.region == region)
        if provider:
            query = query.join(Document, Item.document_id == Document.id).where(
                Document.provider == provider
            )
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(Item.created_at.desc(), Item.id).offset(offset).limit(50))
        return {"total": total, "items": [record(i) if current == "admin" else {
            "id": i.id, "title": "已归集信息（展示模式已脱敏）",
            "created_at": i.created_at, "is_demo": i.is_demo,
        } for i in rows]}


@app.get("/api/v1/display/feed")
def display_feed(after: float = Query(ge=0, allow_inf_nan=False), after_id: str = "", current=Depends(role)):
    with Session() as db:
        rows = db.scalars(unique_items(False).where(
            (Item.created_at > after) | ((Item.created_at == after) & (Item.id > after_id))
        ).order_by(Item.created_at, Item.id).limit(100)).all()
        return {"items": [record(i) if current == "admin" else {
            "id": i.id, "title": "已归集信息", "created_at": i.created_at, "is_demo": False,
        } for i in rows], "after": rows[-1].created_at if rows else after,
            "after_id": rows[-1].id if rows else after_id}


@app.get("/api/v1/display/snapshot")
def snapshot(demo: bool = False, current=Depends(role)):
    now = time.time()
    with Session() as db:
        counts = dict(
            db.execute(
                select(Task.status, func.count()).where(Task.id.in_(public_tasks()), Task.is_demo == demo).group_by(Task.status)
            ).all()
        )
        recent = db.scalars(
            pending_items(demo).order_by(Item.created_at.desc(), Item.id).limit(20)
        ).all()
        latest = db.scalars(
            select(Event).where(Event.task_id.in_(public_tasks()), Event.is_demo == demo).order_by(Event.id.desc()).limit(30)
        ).all()
        # Events are persisted facts; counters never depend on frame rate or animation.
        start = int(now // 60) * 60 - 29 * 60
        events = db.execute(
            select(Event.created_at, Event.kind).where(
                Event.task_id.in_(public_tasks()), Event.is_demo == demo,
                Event.created_at >= start,
                Event.kind.in_(["item.created", "task.succeeded", "task.failed"]),
            )
        ).all()
        buckets = [[start + i * 60, 0, 0, 0] for i in range(30)]
        for timestamp, kind in events:
            index = int((timestamp - start) // 60)
            if 0 <= index < len(buckets):
                buckets[index][
                    {"item.created": 1, "task.succeeded": 2, "task.failed": 3}[kind]
                ] += 1
        return {
            "mode": "demo" if demo else "live",
            "server_time": now,
            "cursor": max((e.id for e in latest), default=0),
            "task_counts": counts,
            "item_count": db.scalar(
                select(func.count(func.distinct(Item.url))).where(Item.is_demo == demo, Item.quality_status == "active")
            ),
            "trend": buckets,
            **chart_facts(db, demo, start),
            **discovery_facts(db, demo, now),
            "delivery": {"available": False, "sent": None},
            **assignment_facts(db, demo, now, current == "admin"),
            "regions": [{"name": r, "count": n} for r, n in db.execute(
                select(Item.region, func.count()).where(Item.id.in_(unique_items(demo).with_only_columns(Item.id)), Item.region.is_not(None)).group_by(Item.region)
            )],
            "region_unknown": db.scalar(select(func.count()).select_from(unique_items(demo).where(Item.region.is_(None)).subquery())),
            "task_scatter": [{"time": t.created_at, "duration": max(0, (t.updated_at if t.status in ("succeeded", "failed", "action_required") else now) - t.created_at), "status": t.status, "attempts": t.attempts, "kind": t.kind} for t in db.scalars(select(Task).where(Task.id.in_(public_tasks()), Task.is_demo == demo, Task.created_at >= start).order_by(Task.created_at.desc()).limit(300))],
            "collectors": collector_status(db, demo, current),
            "items": [
                record(i)
                if current == "admin"
                else {
                    "id": i.id,
                    "title": "已归集信息（展示模式已脱敏）",
                    "created_at": i.created_at,
                    "is_demo": i.is_demo,
                }
                for i in recent
            ],
            "events": [
                {
                    "id": e.id,
                    "task_id": e.task_id,
                    "kind": e.kind,
                    "created_at": e.created_at,
                    "is_demo": e.is_demo,
                }
                for e in latest
            ],
        }


@app.get("/api/v1/display/events")
async def stream(
    request: Request, demo: bool = False, after: int = Query(0, ge=0), current=Depends(role)
):
    async def events():
        cursor = after

        def batch():
            with Session() as db:
                return [
                    record(e, ("data",))
                    for e in db.scalars(
                        select(Event)
                        .where(Event.id > cursor, Event.task_id.in_(public_tasks()), Event.is_demo == demo)
                        .order_by(Event.id)
                        .limit(100)
                    )
                ]

        while not await request.is_disconnected():
            rows = await asyncio.to_thread(batch)
            for e in rows:
                cursor = e["id"]
                yield f"id: {cursor}\nevent: execution\ndata: {json.dumps(e)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class CustomerInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=5)
    website: str | None = Field(default=None, max_length=1000)
    identity_source: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("请输入完整客户名称")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value):
        if any(not 2 <= len(v.strip()) <= 120 for v in value):
            raise ValueError("简称须为2至120个字")
        return list(dict.fromkeys(v.strip() for v in value))

    @field_validator("website", "identity_source")
    @classmethod
    def safe_url(cls, value):
        from scout.providers import ProviderError, canonical_url
        if not value:
            return None
        try:
            return canonical_url(value)
        except ProviderError:
            raise ValueError("请输入有效的公开网址") from None


@app.get("/api/v1/customers", dependencies=[Depends(admin)])
def list_customers():
    from scout.customers import customer_records
    with Session() as db:
        return customer_records(db)


@app.post("/api/v1/customers", status_code=201, dependencies=[Depends(admin)])
def create_customer(body: CustomerInput):
    from sqlalchemy.exc import IntegrityError

    from scout.customers import queries
    try:
        with Session.begin() as db:
            customer = Customer(**body.model_dump())
            db.add(customer)
            db.flush()
            rule = Rule(name=customer.name, query=queries(customer), provider="searxng",
                source_type="customer_watch", customer_id=customer.id, enabled=True,
                interval_seconds=0, max_results=20)
            db.add(rule)
            db.flush()
            return {**record(customer), "rule_id": rule.id, "enabled": True}
    except IntegrityError:
        raise HTTPException(409, "此客户已存在，请直接查看或启用现有监测") from None


@app.get("/api/v1/customer-signals")
def customer_signals(customer_id: str | None = None, offset: int = Query(0, ge=0), current=Depends(role)):
    from scout.customers import signal_window
    with Session() as db:
        query = select(CustomerSignal, Customer, Document).join(Customer, Customer.id == CustomerSignal.customer_id).join(Document, Document.id == CustomerSignal.document_id).where(*signal_window())
        if customer_id:
            query = query.where(Customer.id == customer_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(CustomerSignal.created_at.desc(), CustomerSignal.id).offset(offset).limit(30))
        return {"total": total, "items": [
            {**record(s), "customer_name": c.name, "title": d.title, "content_kind": d.content_kind}
            if current == "admin" else {"id": s.id, "customer_name": "客户已脱敏", "title": "客户动态已脱敏",
                "topic": s.topic, "published_at": s.published_at, "created_at": s.created_at}
            for s, c, d in rows]}


@app.get("/api/v1/customer-signals/{signal_id}", dependencies=[Depends(admin)])
def customer_signal_detail(signal_id: str):
    with Session() as db:
        signal = db.get(CustomerSignal, signal_id)
        if not signal:
            raise HTTPException(404, "客户动态不存在")
        return {**record(signal), "evidence": record(db.get(Document, signal.document_id))}


@app.post("/api/v1/xiaohongshu/login/status", dependencies=[Depends(admin)])
def xhs_login_status():
    from scout.providers import ProviderError
    from scout.xiaohongshu import login_status
    try:
        result = login_status(settings())
    except ProviderError as exc:
        raise HTTPException(503, exc.code) from None
    if result["is_logged_in"]:
        with Session.begin() as db:
            for rule in db.scalars(select(Rule).where(Rule.provider == "xiaohongshu", Rule.enabled.is_(True))):
                rule.next_run_at = time.time()
            for task in db.scalars(select(Task).where(Task.payload["provider"].as_string() == "xiaohongshu",
                    Task.status == "action_required", Task.error_code.in_(("xhs_login_required", "xhs_verification_required"))).with_for_update()):
                task.status, task.error_code = "queued", None
                task.available_at = time.time()
                task.attempt_limit = task.attempts + settings().max_attempts
                db.get(Outbox, task.id).next_publish_at = time.time()
                emit(db, task, "task.queued", session_restored=True)
    return result


@app.post("/api/v1/xiaohongshu/login/qrcode", dependencies=[Depends(admin)])
def xhs_login_qrcode():
    from scout.providers import ProviderError
    from scout.xiaohongshu import login_qrcode
    try:
        return login_qrcode(settings())
    except ProviderError as exc:
        raise HTTPException(503, exc.code) from None


@app.get("/api/v1/xiaohongshu", dependencies=[Depends(admin)])
def xhs_overview():
    with Session() as db:
        rows = db.scalars(select(Rule).where(Rule.provider == "xiaohongshu").order_by(Rule.created_at)).all()
        ids = {r.id for r in rows}
        return {"rules": [record(r) for r in rows],
                "collectors": [c for c in collector_status(db, False, "admin") if c["id"] in ids]}
