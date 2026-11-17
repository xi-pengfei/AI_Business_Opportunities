"""One information record, with delivery state projected onto every view."""

from sqlalchemy import func, select

from scout.models import Customer, CustomerSignal, Delivery, Document, Item, Rule, Task, User

SOURCES = {"public_tender": "商机", "social_demand": "小红书", "customer_watch": "监控"}


def owner_names(db, item_ids):
    """批量解析采集人（=词条负责人）：普通条目走 Task.result.item_id → Task.rule_id，
    客户监控条目走 CustomerSignal → Customer → Rule.customer_id，
    两条路都归到 Rule.owner_user_id；同一条目取最新任务对应的负责人。
    tasks 表无 item_id 索引，必须整批一次查询，逐条调用会全表扫 N 次。"""
    ids = list({i for i in item_ids if i})
    if not ids:
        return {}
    who = func.coalesce(func.nullif(User.display_name, ""), User.username)
    out = {}
    for item_id, name in db.execute(
        select(Task.result["item_id"].as_string(), who)
        .join(Rule, Rule.id == Task.rule_id)
        .join(User, User.id == Rule.owner_user_id)
        .where(Task.result["item_id"].as_string().in_(ids))
        .order_by(Task.created_at.desc())
    ):
        if item_id and item_id not in out:
            out[item_id] = name
    rest = [i for i in ids if i not in out]
    if rest:
        for item_id, name in db.execute(
            select(CustomerSignal.id, who)
            .join(Customer, Customer.id == CustomerSignal.customer_id)
            .join(Rule, Rule.customer_id == Customer.id)
            .join(User, User.id == Rule.owner_user_id)
            .where(CustomerSignal.id.in_(rest))
        ):
            out[item_id] = name
    return out


def owner_name(db, item_id):
    """单条解析（详情页用）；列表接口必须用 owner_names 批量版。"""
    return owner_names(db, [item_id]).get(item_id)


def item_record(db, item, admin=True, owners=None):
    row = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    delivery = db.get(Delivery, item.id)
    news = item.information_kind == "customer_update"
    state = "collected"
    if delivery:
        state = {
            "accepted": "sent" if news else "waiting_claim",
            "sent": "sent" if news else "waiting_claim",
            "read": "sent" if news else "waiting_claim",
            "claimed": "claimed",
            "sending": "sending",
            "unknown": "unknown",
            "failed": "failed",
            "restored": "restored",
        }.get(delivery.status, "collected")
    if item.quality_status in ("review_pending", "review_required"):
        state = item.quality_status
    if item.quality_status == "merged":
        state = "merged"
    owner = owners.get(item.id) if owners is not None else None
    if owner is None:
        owner = owner_name(db, item.id)
    row.update(
        source_name=SOURCES.get(item.source_type, item.source_type),
        business_status=state,
        requires_claim=not news,
        sent_at=delivery.sent_at if delivery else None,
        claimed_by=delivery.claimed_by_name if delivery and not news else None,
        claimed_at=delivery.claimed_at if delivery and not news else None,
        delivery_status=delivery.status if delivery else None,
        owner_name=owner,
    )
    # 展示模式不再脱敏：所有调用方都看到完整条目（admin 参数仅为兼容保留）。
    return row


def sync_customer_item(db, signal):
    """CustomerSignal holds matching evidence; Item is the shared information flow."""
    from sqlalchemy import select

    doc = db.get(Document, signal.document_id)
    item = db.scalar(select(Item).where(Item.id == signal.id))
    is_new = item is None
    if is_new:
        item = Item(
            id=signal.id,
            document_id=doc.id,
            title=doc.title,
            url=signal.url,
            text=doc.raw_content,
            source_type="customer_watch",
            information_kind="customer_update",
            contacts=[],
            is_demo=False,
        )
        db.add(item)
    if not is_new and item.document_id == doc.id:
        return item
    item.document_id = doc.id
    item.fragments = signal.fragments
    item.category = signal.topic
    item.published_at = signal.published_at
    item.quality_status = "review_pending" if signal.quality_status == "active" else signal.quality_status
    item.ai_review = {}
    item.quality_reason = "ai_review_required" if signal.quality_status == "active" else signal.quality_reason
    item.created_at = signal.created_at
    db.flush()
    return item
