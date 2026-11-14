import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Rule(Base):
    __tablename__ = "monitor_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(String(500))
    provider: Mapped[str] = mapped_column(String(30), default="tavily")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    max_results: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
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
    information_kind: Mapped[str] = mapped_column(String(20), default="bulletin", server_default="bulletin")
    contacts: Mapped[list] = mapped_column(JSON, default=list)
    quality_status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
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
