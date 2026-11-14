import asyncio
import json
import secrets
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text

from scout.config import settings
from scout.db import Session
from scout.display import chart_facts, collector_status, discovery_facts, unique_items
from scout.models import Attempt, Document, Event, Item, Outbox, Rule, Task
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
    provider: Literal["searxng", "tavily", "demo"] = "searxng"
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
            record(r) for r in db.scalars(select(Rule).order_by(Rule.created_at.desc()).limit(100))
        ]


@app.post("/api/v1/rules", status_code=201, dependencies=[Depends(admin)])
def create_rule(body: RuleInput):
    if body.provider == "demo" and not settings().allow_demo:
        raise HTTPException(422, "演示适配器未启用")
    with Session.begin() as db:
        rule = Rule(**body.model_dump())
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
def items(demo: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with Session() as db:
        return [
            record(i)
            for i in db.scalars(
                unique_items(demo)
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
    offset: int = Query(0, ge=0),
    demo: bool = False,
    current=Depends(role),
):
    if end <= start or end - start > 86400 * 90:
        raise HTTPException(422, "请选择90天以内的有效时间范围")
    with Session() as db:
        query = unique_items(demo).where(Item.created_at >= start, Item.created_at < end)
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


@app.get("/api/v1/display/snapshot")
def snapshot(demo: bool = False, current=Depends(role)):
    now = time.time()
    with Session() as db:
        counts = dict(
            db.execute(
                select(Task.status, func.count()).where(Task.is_demo == demo).group_by(Task.status)
            ).all()
        )
        recent = db.scalars(
            unique_items(demo).order_by(Item.created_at.desc(), Item.id).limit(8)
        ).all()
        latest = db.scalars(
            select(Event).where(Event.is_demo == demo).order_by(Event.id.desc()).limit(30)
        ).all()
        # Events are persisted facts; counters never depend on frame rate or animation.
        start = int(now // 60) * 60 - 29 * 60
        events = db.execute(
            select(Event.created_at, Event.kind).where(
                Event.is_demo == demo,
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
                select(func.count(func.distinct(Item.url))).where(Item.is_demo == demo)
            ),
            "trend": buckets,
            **chart_facts(db, demo, start),
            **discovery_facts(db, demo, now),
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
                        .where(Event.id > cursor, Event.is_demo == demo)
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
