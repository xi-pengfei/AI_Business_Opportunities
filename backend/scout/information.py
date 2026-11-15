"""One information record, with delivery state projected onto every view."""

from scout.models import Delivery, Document, Item

SOURCES = {"public_tender": "商机", "social_demand": "小红书", "customer_watch": "监控"}


def item_record(db, item, admin=True):
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
    row.update(
        source_name=SOURCES.get(item.source_type, item.source_type),
        business_status=state,
        requires_claim=not news,
        sent_at=delivery.sent_at if delivery else None,
        claimed_by=delivery.claimed_by_name if delivery and not news else None,
        claimed_at=delivery.claimed_at if delivery and not news else None,
        delivery_status=delivery.status if delivery else None,
    )
    if not admin:
        row = {
            k: v
            for k, v in row.items()
            if k
            in (
                "id",
                "created_at",
                "is_demo",
                "source_type",
                "source_name",
                "business_status",
                "requires_claim",
                "sent_at",
                "claimed_at",
                "delivery_status",
            )
        }
        row.update(
            title="已归集信息（展示模式已脱敏）",
            claimed_by="群成员" if delivery and delivery.claimed_by_name and not news else None,
        )
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
