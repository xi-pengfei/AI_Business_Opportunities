import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    reference_urls: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Rule(Base):
    __tablename__ = "monitor_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(30), default="public_tender", server_default="public_tender")
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), unique=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    xhs_account_id: Mapped[str | None] = mapped_column(ForeignKey("xhs_accounts.id"), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    search_spec: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    provider: Mapped[str] = mapped_column(String(30), default="tavily")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    max_results: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float)


class XhsAccount(Base):
    """一个独立的小红书连接器实例：自己的登录态 + 自己的关键词规则。"""
    __tablename__ = "xhs_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(500))
    token: Mapped[str] = mapped_column(String(500), default="")
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30))
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("monitor_rules.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_limit: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    lease_until: Mapped[float | None] = mapped_column(Float)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(50))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Attempt(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (UniqueConstraint("task_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[float] = mapped_column(Float, default=time.time)
    ended_at: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(30), default="running")


class Outbox(Base):
    __tablename__ = "task_outbox"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    next_publish_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    publishes: Mapped[int] = mapped_column(Integer, default=0)


class Document(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    identity: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    raw_content: Mapped[str] = mapped_column(Text)
    content_kind: Mapped[str] = mapped_column(String(30))
    content_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(30))
    published_at: Mapped[str | None] = mapped_column(String(100))
    captured_at: Mapped[float] = mapped_column(Float, default=time.time)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Item(Base):
    __tablename__ = "information_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    fragments: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    category: Mapped[str] = mapped_column(String(30), default="其他信息", server_default="其他信息")
    source_type: Mapped[str] = mapped_column(String(30), default="public_tender", server_default="public_tender")
    information_kind: Mapped[str] = mapped_column(String(20), default="bulletin", server_default="bulletin")
    contacts: Mapped[list] = mapped_column(JSON, default=list)
    quality_status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    related_item_id: Mapped[str | None] = mapped_column(ForeignKey("information_items.id"), index=True)
    relation_kind: Mapped[str | None] = mapped_column(String(20))
    source_urls: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    ai_review: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    quality_reason: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(20))
    region_evidence: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[str | None] = mapped_column(String(30))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class Event(Base):
    __tablename__ = "execution_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class Delivery(Base):
    __tablename__ = "information_deliveries"
    item_id: Mapped[str] = mapped_column(ForeignKey("information_items.id"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(300))
    robot_code: Mapped[str] = mapped_column(String(120))
    recipient: Mapped[str] = mapped_column(String(120), default="钉钉群")
    status: Mapped[str] = mapped_column(String(30), default="sending")
    message_id: Mapped[str | None] = mapped_column(String(500), unique=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    sent_at: Mapped[float | None] = mapped_column(Float)
    read_at: Mapped[float | None] = mapped_column(Float)
    claim_code: Mapped[str | None] = mapped_column(String(20), unique=True, default=lambda: uuid.uuid4().hex[:12])
    claimed_by_id: Mapped[str | None] = mapped_column(String(200))
    claimed_by_name: Mapped[str | None] = mapped_column(String(120))
    claimed_at: Mapped[float | None] = mapped_column(Float)
    claim_message_id: Mapped[str | None] = mapped_column(String(500), unique=True)
    next_check_at: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str | None] = mapped_column(String(60))


class DeliveryGate(Base):
    __tablename__ = "delivery_gates"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    current_item_id: Mapped[str | None] = mapped_column(ForeignKey("information_items.id"))


class RemovedEvidence(Base):
    __tablename__ = "removed_evidence"
    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)


class SearchCursor(Base):
    __tablename__ = "search_cursors"
    __table_args__ = (UniqueConstraint("rule_id", "config_version", "query", "engine"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("monitor_rules.id"), index=True)
    config_version: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(String(500))
    engine: Mapped[str] = mapped_column(String(40))
    page: Mapped[int] = mapped_column(Integer, default=1)
    empty_streak: Mapped[int] = mapped_column(Integer, default=0)
    signature: Mapped[str | None] = mapped_column(String(64))
    next_at: Mapped[float] = mapped_column(Float, default=0, index=True)
    last_front_at: Mapped[float] = mapped_column(Float, default=0)
    last_result_at: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(40), default="new")


class CustomerSignal(Base):
    __tablename__ = "customer_signals"
    __table_args__ = (UniqueConstraint("customer_id", "url"), UniqueConstraint("customer_id", "content_hash"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(String(30))
    matched_name: Mapped[str] = mapped_column(String(120))
    fragments: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[str | None] = mapped_column(String(30))
    quality_status: Mapped[str] = mapped_column(String(20))
    quality_reason: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class BacklogSample(Base):
    __tablename__ = "business_backlog_samples"
    minute: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    pending: Mapped[int] = mapped_column(Integer)
    waiting_claim: Mapped[int] = mapped_column(Integer)


class DingTalkGroup(Base):
    __tablename__ = "dingtalk_discovered_groups"
    conversation_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    robot_code: Mapped[str] = mapped_column(String(120))
    requested_at: Mapped[float] = mapped_column(Float)


class ConsoleToken(Base):
    """Rotated access tokens; overrides .env values while a row exists."""
    __tablename__ = "console_tokens"
    purpose: Mapped[str] = mapped_column(String(30), primary_key=True)
    token: Mapped[str] = mapped_column(String(120))
    rotated_at: Mapped[float] = mapped_column(Float, default=time.time)


class User(Base):
    """本机账号：密码登录 + 外部身份挂载（钉钉/飞书/企微），无渠道特权。"""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class UserIdentity(Base):
    """一个账号可绑定多个外部渠道；三家同权重，登录方式与身份挂载都走这里。"""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "open_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    open_id: Mapped[str] = mapped_column(String(128))
    union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bound_at: Mapped[float] = mapped_column(Float, default=time.time)


class ApiKey(Base):
    """个人级 API 密钥（ska_ 前缀明文只显示一次），替代旧的全局 ADMIN_TOKEN 供脚本使用。"""

    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_used_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class InviteToken(Base):
    """一次性邀请：管理员建号后生成链接，员工打开链接扫码绑定钉钉身份（唯一绑定入口）。

    用过即失效（used_at）；同一账号签发新邀请时旧邀请立即过期，避免多条活链接。
    """

    __tablename__ = "invite_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(20), default="dingtalk", server_default="dingtalk")
    expires_at: Mapped[float] = mapped_column(Float)
    used_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
