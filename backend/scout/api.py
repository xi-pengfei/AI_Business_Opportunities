import asyncio
import json
import logging
import secrets
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, text

from scout import auth, dingtalk_sso
from scout.assignments import assignment_facts, pending_items
from scout.config import settings
from scout.db import Session
from scout.display import chart_facts, collector_status, discovery_facts, public_tasks, unique_items
from scout.flow_metrics import flow_facts
from scout.information import item_record, owner_names
from scout.models import (
    ApiKey,
    Attempt,
    ConsoleToken,
    Customer,
    CustomerSignal,
    Document,
    Event,
    InviteToken,
    Item,
    Outbox,
    Rule,
    Task,
    User,
    UserIdentity,
)
from scout.product_rules import ProductInput, ProductSpec
from scout.service import emit, start_rule

app = FastAPI(title="AI商机智能体", version="0.1.0")

log = logging.getLogger(__name__)


@app.on_event("startup")
def bootstrap_admin():
    """首次启动种子系统管理员；此后账号完全由 users 表管理。"""
    try:
        auth.ensure_bootstrap()
    except Exception:
        log.exception("管理员种子失败（users 表可能尚未迁移完成）")


def console_token(purpose: str) -> tuple[str, str]:
    """有效令牌及其来源（"db" / "env"）。管理令牌已下线，仅保留大屏展示令牌。"""
    with Session() as db:
        row = db.get(ConsoleToken, purpose)
        if row and row.token:
            return row.token, "db"
    return settings().display_token, "env"


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


def own_or_admin(rule: Rule, user: User) -> None:
    """规则全员可见（只读），但只能操作自己创建的；管理员不受限。"""
    if user.role == "admin":
        return
    if rule.owner_user_id == user.id:
        return
    raise HTTPException(403, "只能操作自己创建的规则；如需调整他人规则请联系管理员")


# ---------- 登录与会话 ----------


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@app.post("/api/v1/auth/login")
def login(body: LoginInput):
    username = body.username.strip()
    if auth.login_attempts_left(username) <= 0:
        raise HTTPException(429, "失败次数过多，请 15 分钟后再试")
    with Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user or not auth.verify_password(user.password_hash, body.password):
            auth.record_login_failure(username)
            raise HTTPException(401, "用户名或密码不正确")
        if not user.is_active:
            raise HTTPException(403, "账号已被停用，请联系管理员")
    auth.reset_login_failures(username)
    return {"access_token": auth.issue_token(user), "user": auth.user_record(user)}


@app.get("/api/v1/auth/me")
def me(user=Depends(auth.current_user)):
    return auth.user_record(user)


class PasswordInput(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@app.post("/api/v1/auth/change-password")
def change_password(body: PasswordInput, user=Depends(auth.current_user)):
    with Session.begin() as db:
        row = db.get(User, user.id)
        if row is None or not auth.verify_password(row.password_hash, body.old_password):
            raise HTTPException(401, "原密码不正确")
        row.password_hash = auth.hash_password(body.new_password)
    return {"ok": True}


# ---------- 用户管理（系统管理员） ----------


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=80)
    role: Literal["admin", "member"] = "member"

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        """允许中文姓名作用户名，只拒绝空白字符。"""
        name = value.strip()
        if not name:
            raise ValueError("用户名不能为空")
        if any(ch.isspace() for ch in name):
            raise ValueError("用户名不能包含空格")
        return name


@app.get("/api/v1/users", dependencies=[Depends(auth.require_admin)])
def list_users():
    with Session() as db:
        bound = set(
            db.scalars(
                select(UserIdentity.user_id).where(UserIdentity.provider == "dingtalk")
            )
        )
        return [
            {**auth.user_record(u), "identities": ["dingtalk"] if u.id in bound else []}
            for u in db.scalars(select(User).order_by(User.created_at))
        ]


@app.post("/api/v1/users", status_code=201, dependencies=[Depends(auth.require_admin)])
def create_user(body: UserCreate):
    with Session.begin() as db:
        if db.scalar(select(User).where(User.username == body.username).limit(1)):
            raise HTTPException(409, "用户名已存在")
        user = User(
            username=body.username,
            password_hash=auth.hash_password(body.password),
            display_name=body.display_name.strip(),
            role=body.role,
            created_at=time.time(),
        )
        db.add(user)
        db.flush()
        return auth.user_record(user)


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None


@app.patch("/api/v1/users/{user_id}", dependencies=[Depends(auth.require_admin)])
def update_user(user_id: str, body: UserPatch):
    with Session.begin() as db:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, "用户不存在")
        demoting = (
            target.role == "admin"
            and target.is_active
            and (body.role == "member" or body.is_active is False)
        )
        if demoting:
            active_admins = db.scalar(
                select(func.count()).select_from(
                    select(User).where(User.role == "admin", User.is_active.is_(True)).subquery()
                )
            )
            if (active_admins or 0) <= 1:
                raise HTTPException(409, "至少保留一名启用的管理员")
        if body.password is not None:
            target.password_hash = auth.hash_password(body.password)
        for field in ("display_name", "role", "is_active"):
            value = getattr(body, field)
            if value is not None:
                setattr(target, field, value)
        return auth.user_record(target)


# ---------- 钉钉扫码登录与一次性邀请绑定 ----------


@app.get("/api/v1/auth/dingtalk/config")
def dingtalk_config(request: Request):
    """公开配置：登录页据此显示扫码按钮并构造跳转地址。"""
    s = settings()
    enabled = bool(s.dingtalk_app_key and s.dingtalk_app_secret)
    redirect_uri = s.dingtalk_redirect_uri or (str(request.base_url).rstrip("/") + "/dingtalk")
    return {
        "enabled": enabled,
        "client_id": s.dingtalk_app_key,
        "scope": s.dingtalk_login_scope,
        "redirect_uri": redirect_uri,
    }


class DingTalkCallbackInput(BaseModel):
    auth_code: str = Field(min_length=1, max_length=400, alias="authCode")
    invite: str | None = Field(default=None, max_length=200)

    model_config = {"populate_by_name": True}


@app.post("/api/v1/auth/dingtalk/callback")
def dingtalk_callback(body: DingTalkCallbackInput):
    """扫码回调：带邀请令牌 → 绑定身份并登录；不带 → 已绑定账号直接登录。"""
    s = settings()
    if not (s.dingtalk_app_key and s.dingtalk_app_secret):
        raise HTTPException(400, "钉钉登录未配置：请在 .env 设置 DINGTALK_APP_KEY / DINGTALK_APP_SECRET")
    try:
        identity = dingtalk_sso.exchange_identity(s.dingtalk_app_key, s.dingtalk_app_secret, body.auth_code)
    except dingtalk_sso.DingTalkError as exc:
        log.warning("钉钉登录链路失败: %s", exc)
        raise HTTPException(502, str(exc))
    now = time.time()
    with Session.begin() as db:
        existing = db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == "dingtalk",
                UserIdentity.open_id == identity["open_id"],
            )
        )
        if body.invite:
            invite = db.scalar(select(InviteToken).where(InviteToken.token == body.invite))
            if invite is None or invite.provider != "dingtalk":
                raise HTTPException(400, "邀请链接无效，请向管理员确认")
            if invite.used_at:
                raise HTTPException(409, "邀请链接已被使用，请联系管理员重新生成")
            if invite.expires_at < now:
                raise HTTPException(409, "邀请链接已过期，请联系管理员重新生成")
            target = db.get(User, invite.user_id)
            if target is None or not target.is_active:
                raise HTTPException(403, "邀请对应的账号不存在或已停用")
            if existing and existing.user_id != target.id:
                raise HTTPException(409, "该钉钉账号已绑定其他用户，如需改绑请联系管理员")
            if existing is None:
                # 邀请即改绑：替换该账号原有的钉钉身份，保持一人一号
                db.execute(
                    delete(UserIdentity).where(
                        UserIdentity.user_id == target.id,
                        UserIdentity.provider == "dingtalk",
                    )
                )
                db.add(
                    UserIdentity(
                        user_id=target.id,
                        provider="dingtalk",
                        open_id=identity["open_id"],
                        union_id=identity["union_id"],
                        bound_at=now,
                    )
                )
            invite.used_at = now
        else:
            if existing is None:
                raise HTTPException(
                    403, "该钉钉尚未绑定任何账号：请先用管理员发送的邀请链接完成绑定"
                )
            target = db.get(User, existing.user_id)
            if target is None or not target.is_active:
                raise HTTPException(403, "账号已被停用，请联系管理员")
    return {"access_token": auth.issue_token(target), "user": auth.user_record(target)}


@app.get("/api/v1/auth/invite-info")
def invite_info(token: str = Query(min_length=1, max_length=200)):
    """邀请链接落地页展示用：告诉访客这是给谁的邀请、是否仍有效。"""
    with Session() as db:
        row = db.scalar(select(InviteToken).where(InviteToken.token == token))
        if row is None:
            raise HTTPException(404, "邀请链接无效，请向管理员确认")
        target = db.get(User, row.user_id)
        return {
            "provider": row.provider,
            "display_name": (target.display_name or target.username) if target else "",
            "used": bool(row.used_at),
            "expired": row.expires_at < time.time(),
        }


class InviteLinkInput(BaseModel):
    provider: Literal["dingtalk"] = "dingtalk"


@app.post("/api/v1/users/{user_id}/invite-link", status_code=201)
def create_invite_link(user_id: str, body: InviteLinkInput, admin=Depends(auth.require_admin)):
    """管理员生成一次性邀请链接；旧邀请立即作废，7 天有效。"""
    with Session.begin() as db:
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, "用户不存在")
        if not target.is_active:
            raise HTTPException(400, "账号已停用，请先启用再发邀请")
        for row in db.scalars(
            select(InviteToken).where(
                InviteToken.user_id == user_id,
                InviteToken.provider == body.provider,
                InviteToken.used_at.is_(None),
            )
        ):
            row.expires_at = time.time() - 1
        invite = InviteToken(
            token=secrets.token_urlsafe(24),
            user_id=user_id,
            created_by=admin.id,
            provider=body.provider,
            expires_at=time.time() + 7 * 24 * 3600,
            created_at=time.time(),
        )
        db.add(invite)
        db.flush()
        return {"token": invite.token, "expires_at": invite.expires_at}


# ---------- 个人 API 密钥（替代旧 ADMIN_TOKEN 供脚本使用） ----------


class ApiKeyInput(BaseModel):
    name: str = Field(default="", max_length=80)


@app.get("/api/v1/api-keys")
def list_api_keys(user=Depends(auth.current_user)):
    with Session() as db:
        rows = db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.revoked.is_(False))
            .order_by(ApiKey.created_at.desc())
        )
        return [
            {"id": k.id, "name": k.name, "prefix": k.prefix, "created_at": k.created_at, "last_used_at": k.last_used_at}
            for k in rows
        ]


@app.post("/api/v1/api-keys", status_code=201)
def create_api_key(body: ApiKeyInput, user=Depends(auth.current_user)):
    plain, info = auth.new_api_key(user.id, body.name)
    return {**info, "key": plain}


@app.delete("/api/v1/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: str, user=Depends(auth.current_user)):
    with Session.begin() as db:
        row = db.get(ApiKey, key_id)
        if row is None:
            raise HTTPException(404, "密钥不存在")
        if row.user_id != user.id and user.role != "admin":
            raise HTTPException(403, "只能管理自己的密钥")
        row.revoked = True


# ---------- 大屏令牌（屏幕场景保留；管理令牌已下线，由账号体系替代） ----------


@app.get("/api/v1/console-token", dependencies=[Depends(auth.require_admin)])
def read_console_token(reveal: bool = False):
    token, source = console_token("display")
    payload = {"masked": masked(token), "source": source, "present": bool(token)}
    if reveal and token:
        payload["token"] = token
    return payload


@app.post("/api/v1/console-token/rotate", dependencies=[Depends(auth.require_admin)])
def rotate_display_token():
    if not console_token("display")[0]:
        raise HTTPException(404, "尚未配置展示令牌")
    token = rotate_console_token("display")
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


@app.get("/api/v1/providers", dependencies=[Depends(auth.current_user)])
def providers():
    return {
        "searxng": {"configured": bool(settings().searxng_url)},
        "tavily": {"configured": bool(settings().tavily_api_key)},
        "demo": {"enabled": settings().allow_demo},
    }


@app.get("/api/v1/rules", dependencies=[Depends(auth.current_user)])
def rules():
    with Session() as db:
        return [
            record(r) for r in db.scalars(select(Rule).where(Rule.source_type.in_(("public_tender", "social_demand"))).order_by(Rule.created_at.desc()).limit(100))
        ]


@app.post("/api/v1/rules/review", dependencies=[Depends(auth.current_user)])
def review_rule(body: RuleInput):
    from scout.keyword_review import review
    try:
        return review(body.name, body.query, settings())
    except Exception:
        raise HTTPException(503, "AI检查暂时不可用，配置未保存、未启动，请稍后重试") from None




@app.post("/api/v1/network-rules/review", dependencies=[Depends(auth.current_user)])
def review_product_rule(body: ProductSpec):
    from scout.product_rules import review_product
    try:
        return review_product(body, settings())
    except Exception:
        raise HTTPException(503, "AI检查暂时不可用，尚未保存或启动") from None


def synonym_duplicates(db, spec: ProductSpec, exclude_id: str | None) -> list[dict]:
    """撞库：找出同义词与现有词条重叠的其他规则，提示但不阻止保存。"""
    wanted = {s.casefold() for s in spec.synonyms}
    if not wanted:
        return []
    rows = db.execute(
        select(Rule, User.display_name)
        .outerjoin(User, User.id == Rule.owner_user_id)
        .where(Rule.source_type == "public_tender", Rule.provider != "demo")
    ).all()
    hits: dict[str, dict] = {}
    for rule, owner_name in rows:
        if rule.id == exclude_id or (rule.search_spec or {}).get("retired"):
            continue
        theirs = {s.casefold() for s in (rule.search_spec or {}).get("synonyms", [])}
        overlap = sorted(wanted & theirs)
        if overlap:
            hits[rule.id] = {
                "id": rule.id,
                "name": rule.name,
                "owner": owner_name or "系统",
                "overlap": overlap[:4],
            }
    return list(hits.values())[:3]


def save_product_rule(body, rule_id=None, user=None):
    spec = ProductSpec.model_validate(body.model_dump())
    with Session.begin() as db:
        rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update()) if rule_id else None
        if rule_id and (not rule or rule.source_type != "public_tender" or (rule.search_spec or {}).get("retired")):
            raise HTTPException(404, "网络采集词条不存在")
        if rule is not None:
            own_or_admin(rule, user)
        others = db.scalars(select(Rule).where(Rule.source_type == "public_tender", Rule.provider != "demo")).all()
        if any(r.id != rule_id and not (r.search_spec or {}).get("retired") and r.name.casefold() == spec.product.casefold() for r in others):
            raise HTTPException(409, "已存在同名产品，请修改现有词条")
        if rule is None:
            rule = Rule(source_type="public_tender")
            db.add(rule)
        else:
            rule.version += 1
        rule.name = spec.product
        rule.search_spec = spec.model_dump()
        rule.query = "\n".join(spec.searches())
        rule.provider = "searxng"
        rule.interval_seconds = 0
        rule.max_results = 20
        if rule.owner_user_id is None and user is not None:
            rule.owner_user_id = user.id
        if body.enabled and not rule.started_at:
            rule.started_at = time.time()
        rule.enabled = body.enabled
        rule.next_run_at = time.time()
        db.flush()
        return {**record(rule), "duplicates": synonym_duplicates(db, spec, rule.id)}


@app.post("/api/v1/network-rules", status_code=201, dependencies=[Depends(auth.current_user)])
def create_product_rule(body: ProductInput, user=Depends(auth.current_user)):
    return save_product_rule(body, user=user)


@app.patch("/api/v1/network-rules/{rule_id}", dependencies=[Depends(auth.current_user)])
def edit_product_rule(rule_id: str, body: ProductInput, user=Depends(auth.current_user)):
    return save_product_rule(body, rule_id, user)


@app.get("/api/v1/network-rules/stats", dependencies=[Depends(auth.current_user)])
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


@app.post("/api/v1/rules", status_code=201, dependencies=[Depends(auth.current_user)])
def create_rule(body: RuleInput, user=Depends(auth.current_user)):
    if body.provider == "demo" and not settings().allow_demo:
        raise HTTPException(422, "演示适配器未启用")
    with Session.begin() as db:
        rule = Rule(
            **body.model_dump(),
            source_type="social_demand" if body.provider == "xiaohongshu" else "public_tender",
            owner_user_id=user.id,
        )
        db.add(rule)
        db.flush()
        return record(rule)


@app.patch("/api/v1/rules/{rule_id}", dependencies=[Depends(auth.current_user)])
def enable_rule(rule_id: str, body: EnableInput, user=Depends(auth.current_user)):
    with Session.begin() as db:
        rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())
        if not rule:
            raise HTTPException(404, "规则不存在")
        own_or_admin(rule, user)
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


@app.post("/api/v1/rules/{rule_id}/run", status_code=202, dependencies=[Depends(auth.current_user)])
def run_rule(rule_id: str, idempotency_key: Annotated[str, Header(min_length=1, max_length=100)], user=Depends(auth.current_user)):
    with Session.begin() as db:
        rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())
        if not rule:
            raise HTTPException(404, "规则不存在")
        own_or_admin(rule, user)
        return task_record(start_rule(db, rule, f"manual:{rule_id}:{idempotency_key}"))


@app.get("/api/v1/tasks", dependencies=[Depends(auth.current_user)])
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


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(auth.current_user)])
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


@app.post("/api/v1/tasks/{task_id}/retry", status_code=202, dependencies=[Depends(auth.current_user)])
def retry_task(task_id: str, user=Depends(auth.current_user)):
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if not task:
            raise HTTPException(404, "任务不存在")
        if task.rule_id:
            rule = db.get(Rule, task.rule_id)
            if rule:
                own_or_admin(rule, user)
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


@app.get("/api/v1/items", dependencies=[Depends(auth.current_user)])
def items(demo: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
          status: Literal["active", "archived", "review_pending", "review_required", "merged"] = "active"):

    with Session() as db:
        rows = db.scalars(
            (unique_items(demo) if status == "active" else
             select(Item).where(Item.is_demo == demo, Item.quality_status == status))
            .order_by(Item.created_at.desc(), Item.id)
            .offset(offset)
            .limit(limit)
        ).all()
        owners = owner_names(db, [i.id for i in rows])
        return [item_record(db, i, owners=owners) for i in rows]


@app.post("/api/v1/items/{item_id}/review", dependencies=[Depends(auth.require_admin)])
def retry_review(item_id: str):
    with Session.begin() as db:
        item = db.get(Item, item_id)
        if not item or item.information_kind not in ("opportunity", "demand", "customer_update") or item.quality_status != "review_required":
            raise HTTPException(409, "仅待核实的商机候选可重新审核")
        item.ai_review = {}
        item.quality_status, item.quality_reason = "review_pending", "ai_review_required"
        return {"status": "review_pending"}


@app.get("/api/v1/items/{item_id}", dependencies=[Depends(auth.current_user)])
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
    current=Depends(auth.screen),
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
        rows = db.scalars(query.order_by(Item.created_at.desc(), Item.id).offset(offset).limit(50)).all()
        owners = owner_names(db, [i.id for i in rows])
        # 展示令牌与管理台看到同一份数据：不再做条目脱敏。
        return {"total": total, "items": [item_record(db, i, owners=owners) for i in rows]}


@app.get("/api/v1/display/feed")
def display_feed(after: float = Query(ge=0, allow_inf_nan=False), after_id: str = "", current=Depends(auth.screen)):
    with Session() as db:
        available_at = func.coalesce(Item.ai_review["reviewed_at"].as_float(), Item.created_at)
        rows = db.scalars(unique_items(False).where(
            (available_at > after) | ((available_at == after) & (Item.id > after_id))
        ).order_by(available_at, Item.id).limit(100)).all()
        owners = owner_names(db, [i.id for i in rows])
        return {"items": [item_record(db, i, owners=owners) for i in rows], "after": (rows[-1].ai_review.get("reviewed_at") or rows[-1].created_at) if rows else after,
            "after_id": rows[-1].id if rows else after_id}


@app.get("/api/v1/display/snapshot")
def snapshot(demo: bool = False, current=Depends(auth.screen)):
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
        recent_owners = owner_names(db, [i.id for i in recent])
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
            **flow_facts(db, demo, now, True),
            **discovery_facts(db, demo, now),
            "delivery": {"available": False, "sent": None},
            **assignment_facts(db, demo, now, True),
            "regions": [{"name": r, "count": n} for r, n in db.execute(
                select(Item.region, func.count()).where(Item.id.in_(unique_items(demo).with_only_columns(Item.id)), Item.information_kind.in_(("opportunity", "demand")), Item.region.is_not(None)).group_by(Item.region)
            )],
            "region_unknown": db.scalar(select(func.count()).select_from(unique_items(demo).where(Item.information_kind.in_(("opportunity", "demand")), Item.region.is_(None)).subquery())),
            "task_scatter": [{"time": t.created_at, "duration": max(0, (t.updated_at if t.status in ("succeeded", "failed", "action_required") else now) - t.created_at), "status": t.status, "attempts": t.attempts, "kind": t.kind} for t in db.scalars(select(Task).where(Task.id.in_(public_tasks()), Task.is_demo == demo, Task.created_at >= start).order_by(Task.created_at.desc()).limit(300))],
            "collectors": collector_status(db, demo, "admin"),
            # 展示令牌与管理台看到同一份信息条目：不再替换标题。
            "items": [item_record(db, i, owners=recent_owners) for i in recent],
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
    request: Request, demo: bool = False, after: int = Query(0, ge=0), current=Depends(auth.screen)
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
    # 批量导入时可指定对接人（仅管理员）；不填默认为创建人
    owner_user_id: str | None = Field(default=None, max_length=36)

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
            raise ValueError("其他叫法须为2至120个字")
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


@app.get("/api/v1/customers", dependencies=[Depends(auth.current_user)])
def list_customers():
    from scout.customers import customer_records
    with Session() as db:
        return customer_records(db)


@app.post("/api/v1/customers", status_code=201, dependencies=[Depends(auth.current_user)])
def create_customer(body: CustomerInput, user=Depends(auth.current_user)):
    from sqlalchemy.exc import IntegrityError

    from scout.customers import queries
    owner_user_id = user.id
    if body.owner_user_id:
        if user.role != "admin":
            raise HTTPException(403, "只有管理员可以在创建时指定对接人")
        with Session() as check:
            owner = check.get(User, body.owner_user_id)
        if owner is None or not owner.is_active:
            raise HTTPException(422, "对接人不存在或已停用")
        owner_user_id = body.owner_user_id
    try:
        with Session.begin() as db:
            customer = Customer(**body.model_dump(exclude={"owner_user_id"}))
            db.add(customer)
            db.flush()
            rule = Rule(name=customer.name, query=queries(customer), provider="searxng",
                source_type="customer_watch", customer_id=customer.id, enabled=True,
                interval_seconds=0, max_results=20, owner_user_id=owner_user_id)
            db.add(rule)
            db.flush()
            return {**record(customer), "rule_id": rule.id, "enabled": True}
    except IntegrityError:
        raise HTTPException(409, "此客户已存在，请直接查看或启用现有监测") from None


@app.patch("/api/v1/customers/{customer_id}", dependencies=[Depends(auth.current_user)])
def update_customer(customer_id: str, body: CustomerInput, user=Depends(auth.current_user)):
    from sqlalchemy.exc import IntegrityError

    from scout.customers import queries
    try:
        with Session.begin() as db:
            customer = db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
            if customer is None:
                raise HTTPException(404, "客户不存在")
            rule = db.scalar(select(Rule).where(Rule.customer_id == customer_id).with_for_update())
            if rule is not None:
                own_or_admin(rule, user)
            for key in body.model_fields_set:
                if key == "owner_user_id":
                    continue  # 对接人走 batch-owner 或创建时指定，不在修改表单里改
                setattr(customer, key, getattr(body, key))
            rule.name, rule.query = customer.name, queries(customer)
            rule.version += 1
            if rule.enabled:
                rule.next_run_at = time.time()
            db.flush()
            return {**record(customer), "enabled": rule.enabled, "rule_id": rule.id}
    except IntegrityError:
        raise HTTPException(409, "该客户名称已存在") from None


class BatchOwnerInput(BaseModel):
    customer_ids: list[str] = Field(min_length=1, max_length=200)
    owner_user_id: str | None = None


@app.post("/api/v1/customers/batch-owner", dependencies=[Depends(auth.require_admin)])
def batch_assign_owner(body: BatchOwnerInput):
    """批量指定/更换客户对接人：改监测 Rule 的 owner，后续按人推送以此为准。"""
    with Session.begin() as db:
        if body.owner_user_id:
            owner = db.get(User, body.owner_user_id)
            if owner is None or not owner.is_active:
                raise HTTPException(422, "对接人不存在或已停用")
        rows = db.scalars(select(Customer).where(Customer.id.in_(body.customer_ids))).all()
        if len(rows) != len(set(body.customer_ids)):
            raise HTTPException(404, "部分客户不存在，请刷新后重试")
        for customer in rows:
            rule = db.scalar(select(Rule).where(Rule.customer_id == customer.id).with_for_update())
            if rule is not None:
                rule.owner_user_id = body.owner_user_id
        db.flush()
        return {"updated": len(rows), "owner_user_id": body.owner_user_id}


@app.get("/api/v1/customer-signals")
def customer_signals(customer_id: str | None = None, offset: int = Query(0, ge=0), current=Depends(auth.screen)):
    from scout.customers import signal_window
    with Session() as db:
        query = select(CustomerSignal, Customer, Document).join(Customer, Customer.id == CustomerSignal.customer_id).join(Document, Document.id == CustomerSignal.document_id).where(*signal_window())
        if customer_id:
            query = query.where(Customer.id == customer_id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(CustomerSignal.created_at.desc(), CustomerSignal.id).offset(offset).limit(30))
        # 客户监控信号对展示令牌同样显示真实名称与标题（eec8275：展示模式不再脱敏）。
        return {"total": total, "items": [
            {**record(s), "customer_name": c.name, "title": d.title, "content_kind": d.content_kind}
            for s, c, d in rows]}


@app.get("/api/v1/customer-signals/{signal_id}", dependencies=[Depends(auth.current_user)])
def customer_signal_detail(signal_id: str):
    with Session() as db:
        signal = db.get(CustomerSignal, signal_id)
        if not signal:
            raise HTTPException(404, "客户动态不存在")
        return {**record(signal), "evidence": record(db.get(Document, signal.document_id))}


@app.post("/api/v1/xiaohongshu/login/status", dependencies=[Depends(auth.require_admin)])
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


@app.post("/api/v1/xiaohongshu/login/qrcode", dependencies=[Depends(auth.require_admin)])
def xhs_login_qrcode():
    from scout.providers import ProviderError
    from scout.xiaohongshu import login_qrcode
    try:
        return login_qrcode(settings())
    except ProviderError as exc:
        raise HTTPException(503, exc.code) from None


@app.get("/api/v1/xiaohongshu", dependencies=[Depends(auth.require_admin)])
def xhs_overview():
    with Session() as db:
        rows = db.scalars(select(Rule).where(Rule.provider == "xiaohongshu").order_by(Rule.created_at)).all()
        ids = {r.id for r in rows}
        return {"rules": [record(r) for r in rows],
                "collectors": [c for c in collector_status(db, False, "admin") if c["id"] in ids]}


@app.get("/api/v1/dingtalk/groups", dependencies=[Depends(auth.require_admin)])
def discovered_groups():
    from scout.models import DingTalkGroup
    with Session() as db:
        return [{"conversation_id": row.conversation_id, "title": row.title,
                 "requested_at": row.requested_at,
                 "bound": row.conversation_id == settings().dingtalk_conversation_id}
                for row in db.scalars(select(DingTalkGroup).order_by(DingTalkGroup.requested_at.desc()).limit(20))]
