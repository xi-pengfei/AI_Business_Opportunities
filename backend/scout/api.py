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
from scout.flow_metrics import flow_facts
from scout.information import item_record
from scout.models import (
    Attempt,
    ConsoleToken,
    Customer,
    CustomerSignal,
    Document,
    Event,
    Item,
    Outbox,
    Rule,
    Task,
)
from scout.product_rules import ProductInput, ProductSpec
from scout.service import emit, start_rule

app = FastAPI(title="AI商机智能体", version="0.1.0")


def console_token(purpose: str) -> tuple[str, str]:
    """Effective token for a purpose plus where it comes from ("db" or "env")."""
    with Session() as db:
        row = db.get(ConsoleToken, purpose)
        if row and row.token:
            return row.token, "db"
    return (settings().admin_token if purpose == "admin" else settings().display_token), "env"


def rotate_console_token(purpose: str) -> str:
    token = secrets.token_urlsafe(24)
    with Session.begin() as db:
        row = db.get(ConsoleToken, purpose)
        if row:
            row.token = token
            row.rotated_at = time.time()
        else:
            db.add(ConsoleToken(purpose=purpose, token=token, rotated_at=time.time()))
    return token


def masked(token: str) -> str:
    return f"••••••••{token[-4:]}" if len(token) >= 8 else "••••••••"


def role(authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ")
    admin_value, _ = console_token("admin")
    if token and admin_value and secrets.compare_digest(token, admin_value):
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


@app.get("/api/v1/console-token", dependencies=[Depends(admin)])
def read_console_token(reveal: bool = False):
    token, source = console_token("admin")
    if not token:
        raise HTTPException(404, "尚未配置管理员令牌")
    display_value, display_source = console_token("display")
    payload = {
        "masked": masked(token),
        "source": source,
        "display": {
            "masked": masked(display_value) if display_value else "",
            "source": display_source,
            "present": bool(display_value),
        },
    }
    if reveal:
        payload["token"] = token
        if display_value:
            payload["display"]["token"] = display_value
    return payload


@app.post("/api/v1/console-token/rotate", dependencies=[Depends(admin)])
def rotate_admin_token():
    if not console_token("admin")[0]:
        raise HTTPException(404, "尚未配置管理员令牌")
    token = rotate_console_token("admin")
    return {"token": token, "masked": masked(token), "rotated_at": time.time()}


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
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: Literal["searxng", "tavily"] | None = None
    interval_seconds: int | None = Field(default=None, ge=0, le=2592000)
    max_results: int | None = Field(default=None, ge=1, le=20)
    query: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("name", "query")
    @classmethod
    def nonblank_query(cls, value):
        if value is not None and not value.strip():
            raise ValueError("名称和关键词不能为空")
        return value.strip() if value is not None else None


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


@app.post("/api/v1/rules/review", dependencies=[Depends(admin)])
def review_rule(body: RuleInput):
    from scout.keyword_review import review
    try:
        return review(body.name, body.query, settings())
    except Exception:
        raise HTTPException(503, "AI检查暂时不可用，配置未保存、未启动，请稍后重试") from None




@app.post("/api/v1/network-rules/review", dependencies=[Depends(admin)])
def review_product_rule(body: ProductSpec):
    from scout.product_rules import review_product
    try:
        return review_product(body, settings())
    except Exception:
        raise HTTPException(503, "AI检查暂时不可用，尚未保存或启动") from None


def save_product_rule(body, rule_id=None):
    spec=ProductSpec.model_validate(body.model_dump())
    with Session.begin() as db:
        rule=db.scalar(select(Rule).where(Rule.id==rule_id).with_for_update()) if rule_id else None
        if rule_id and (not rule or rule.source_type!='public_tender' or (rule.search_spec or {}).get('retired')):
            raise HTTPException(404, "网络采集词条不存在")
        others=db.scalars(select(Rule).where(Rule.source_type=='public_tender',Rule.provider!='demo')).all()
        if any(r.id!=rule_id and not (r.search_spec or {}).get('retired') and r.name.casefold()==spec.product.casefold() for r in others):
            raise HTTPException(409, "已存在同名产品，请修改现有词条")
        if rule is None:
            rule=Rule(source_type='public_tender')
            db.add(rule)
        else:
            rule.version+=1
        rule.name=spec.product
        rule.search_spec=spec.model_dump()
        rule.query='\n'.join(spec.searches())
        rule.provider='searxng'
        rule.interval_seconds=0
        rule.max_results=20
        if body.enabled and not rule.started_at:
            rule.started_at=time.time()
        rule.enabled=body.enabled
        rule.next_run_at=time.time()
        db.flush()
        return record(rule)


@app.post("/api/v1/network-rules", status_code=201, dependencies=[Depends(admin)])
def create_product_rule(body: ProductInput):
    return save_product_rule(body)


@app.patch("/api/v1/network-rules/{rule_id}", dependencies=[Depends(admin)])
def edit_product_rule(rule_id: str, body: ProductInput):
    return save_product_rule(body, rule_id)


@app.get("/api/v1/network-rules/stats", dependencies=[Depends(admin)])
def network_rule_stats():
    """Per-rule collection footprint: batches, success rate and effective items."""
    with Session() as db:
        rules = db.scalars(
            select(Rule).where(Rule.source_type == "public_tender", Rule.provider != "demo")
        ).all()
        ids = [r.id for r in rules]
        searches = (
            dict(db.execute(select(Task.rule_id, func.count()).where(Task.rule_id.in_(ids), Task.kind == "search").group_by(Task.rule_id)).all())
            if ids
            else {}
        )
        succeeded = (
            dict(
                db.execute(
                    select(Task.rule_id, func.count())
                    .where(Task.rule_id.in_(ids), Task.kind == "search", Task.status == "succeeded")
                    .group_by(Task.rule_id)
                ).all()
            )
            if ids
            else {}
        )
        pairs = (
            db.execute(
                select(Task.rule_id, Task.result["item_id"].as_string()).where(
                    Task.rule_id.in_(ids), Task.result["item_id"].as_string().isnot(None)
                )
            ).all()
            if ids
            else []
        )
        item_ids = {item_id for _, item_id in pairs if item_id}
        quality = (
            dict(db.execute(select(Item.id, Item.quality_status).where(Item.id.in_(item_ids))).all())
            if item_ids
            else {}
        )
        per: dict[str, dict[str, int]] = {}
        seen: set[tuple[str, str]] = set()
        for rule_id, item_id in pairs:
            if not item_id or item_id not in quality or (rule_id, item_id) in seen:
                continue
            seen.add((rule_id, item_id))
            bucket = per.setdefault(rule_id, {"items": 0, "items_total": 0})
            bucket["items_total"] += 1
            if quality[item_id] == "active":
                bucket["items"] += 1
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "started_at": r.started_at,
                "searches": searches.get(r.id, 0),
                "succeeded": succeeded.get(r.id, 0),
                "items": per.get(r.id, {}).get("items", 0),
                "items_total": per.get(r.id, {}).get("items_total", 0),
            }
            for r in rules
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
        if body.provider is not None and rule.source_type != "public_tender":
            raise HTTPException(422, "平台采集请在对应平台页面修改")
        if body.enabled is not None:
            if body.enabled and not rule.enabled:
                rule.started_at = time.time()
            rule.enabled = body.enabled
        for field in ("name", "provider", "interval_seconds", "max_results", "query"):
            value = getattr(body, field)
            if value is not None:
                setattr(rule, field, value)
        rule.version += 1
        if rule.enabled:
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
          status: Literal["active", "archived", "review_pending", "review_required", "merged"] = "active"):

    with Session() as db:
        return [
            item_record(db, i)
            for i in db.scalars(
                (unique_items(demo) if status == "active" else
                 select(Item).where(Item.is_demo == demo, Item.quality_status == status))
                .order_by(Item.created_at.desc(), Item.id)
                .offset(offset)
                .limit(limit)
            )
        ]


@app.post("/api/v1/items/{item_id}/review", dependencies=[Depends(admin)])
def retry_review(item_id: str):
    with Session.begin() as db:
        item = db.get(Item, item_id)
        if not item or item.information_kind not in ("opportunity", "demand", "customer_update") or item.quality_status != "review_required":
            raise HTTPException(409, "仅待核实的商机候选可重新审核")
        item.ai_review = {}
        item.quality_status, item.quality_reason = "review_pending", "ai_review_required"
        return {"status": "review_pending"}


@app.get("/api/v1/items/{item_id}", dependencies=[Depends(admin)])
def item_detail(item_id: str):
    with Session() as db:
        item = db.get(Item, item_id)
        if not item:
            raise HTTPException(404, "信息不存在")
        return {**item_record(db, item), "evidence": record(db.get(Document, item.document_id))}


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
            query = query.where(Item.region == region, Item.information_kind.in_(("opportunity", "demand")))
        if provider:
            query = query.join(Document, Item.document_id == Document.id).where(
                Document.provider == provider
            )
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(Item.created_at.desc(), Item.id).offset(offset).limit(50))
        return {"total": total, "items": [item_record(db, i) if current == "admin" else {
            "id": i.id, "title": "已归集信息（展示模式已脱敏）",
            "created_at": i.created_at, "is_demo": i.is_demo,
        } for i in rows]}


@app.get("/api/v1/display/feed")
def display_feed(after: float = Query(ge=0, allow_inf_nan=False), after_id: str = "", current=Depends(role)):
    with Session() as db:
        available_at = func.coalesce(Item.ai_review["reviewed_at"].as_float(), Item.created_at)
        rows = db.scalars(unique_items(False).where(
            (available_at > after) | ((available_at == after) & (Item.id > after_id))
        ).order_by(available_at, Item.id).limit(100)).all()
        return {"items": [item_record(db, i) if current == "admin" else {
            "id": i.id, "title": "已归集信息", "created_at": i.created_at, "is_demo": False,
        } for i in rows], "after": (rows[-1].ai_review.get("reviewed_at") or rows[-1].created_at) if rows else after,
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
            "active_item_ids": list(db.scalars(unique_items(demo).with_only_columns(Item.id))),
            "server_time": now,
            "cursor": max((e.id for e in latest), default=0),
            "task_counts": counts,
            "item_count": db.scalar(
                select(func.count(func.distinct(Item.url))).where(Item.is_demo == demo, Item.quality_status == "active")
            ),
            "trend": buckets,
            **chart_facts(db, demo, start),
            **flow_facts(db, demo, now, current == "admin"),
            **discovery_facts(db, demo, now),
            "delivery": {"available": False, "sent": None},
            **assignment_facts(db, demo, now, current == "admin"),
            "regions": [{"name": r, "count": n} for r, n in db.execute(
                select(Item.region, func.count()).where(Item.id.in_(unique_items(demo).with_only_columns(Item.id)), Item.information_kind.in_(("opportunity", "demand")), Item.region.is_not(None)).group_by(Item.region)
            )],
            "region_unknown": db.scalar(select(func.count()).select_from(unique_items(demo).where(Item.information_kind.in_(("opportunity", "demand")), Item.region.is_(None)).subquery())),
            "task_scatter": [{"time": t.created_at, "duration": max(0, (t.updated_at if t.status in ("succeeded", "failed", "action_required") else now) - t.created_at), "status": t.status, "attempts": t.attempts, "kind": t.kind} for t in db.scalars(select(Task).where(Task.id.in_(public_tasks()), Task.is_demo == demo, Task.created_at >= start).order_by(Task.created_at.desc()).limit(300))],
            "collectors": collector_status(db, demo, current),
            "items": [
                item_record(db, i)
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
    reference_urls: list[str] = Field(default_factory=list, max_length=10)
    identity_source: str | None = Field(default=None, max_length=1000)

    @field_validator("reference_urls", mode="before")
    @classmethod
    def parse_urls(cls, value):
        import re

        from scout.providers import ProviderError, canonical_url
        if isinstance(value, str):
            value = [s.strip() for s in re.split(r"[\n,，]+", value) if s.strip()]
        if not isinstance(value, list) or any(not isinstance(v, str) or len(v) > 1000 for v in value):
            raise ValueError("请输入网址列表，每个网址最多1000字符")
        try:
            return list(dict.fromkeys(canonical_url(v.strip()) for v in value if isinstance(v, str) and v.strip()))
        except ProviderError:
            raise ValueError("参考网址须为有效的公开网址") from None

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


@app.patch("/api/v1/customers/{customer_id}", dependencies=[Depends(admin)])
def update_customer(customer_id: str, body: CustomerInput):
    from sqlalchemy.exc import IntegrityError

    from scout.customers import queries
    try:
        with Session.begin() as db:
            customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
            if customer is None:
                raise HTTPException(404, "客户不存在")
            rule = db.scalar(select(Rule).where(Rule.customer_id == customer_id).with_for_update())
            for key in body.model_fields_set:
                setattr(customer, key, getattr(body, key))
            rule.name, rule.query = customer.name, queries(customer)
            rule.version += 1
            if rule.enabled:
                rule.next_run_at = time.time()
            db.flush()
            return {**record(customer), "enabled": rule.enabled, "rule_id": rule.id}
    except IntegrityError:
        raise HTTPException(409, "该客户名称已存在") from None


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


@app.get("/api/v1/dingtalk/groups", dependencies=[Depends(admin)])
def discovered_groups():
    from scout.models import DingTalkGroup
    with Session() as db:
        return [{"conversation_id": row.conversation_id, "title": row.title,
                 "requested_at": row.requested_at,
                 "bound": row.conversation_id == settings().dingtalk_conversation_id}
                for row in db.scalars(select(DingTalkGroup).order_by(DingTalkGroup.requested_at.desc()).limit(20))]
