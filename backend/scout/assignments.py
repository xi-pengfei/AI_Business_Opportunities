"""Business backlog counts only undistributed items; transport queues are separate."""

from sqlalchemy import func, select

from scout.information import item_record, owner_names
from scout.models import Delivery, Item

ASSIGNED = ("accepted", "sent", "read", "claimed", "restored")


def pending_items(demo=False, now=None):
    from scout.display import unique_items
    from scout.retention import current_window

    return unique_items(demo).where(
        *((Item.information_kind.in_(("opportunity", "demand")), *current_window(now)) if not demo else ()),
        ~Item.id.in_(select(Delivery.item_id).where(Delivery.status.in_(ASSIGNED)))
    )


def assignment_facts(db, demo, now, admin):
    from scout.config import settings
    from scout.display import unique_items
    from scout.retention import current_window

    config = settings()
    pending = db.scalars(pending_items(demo, now)).all()
    allocated = (
        unique_items(demo)
        .join(Delivery, Delivery.item_id == Item.id)
        .where(Delivery.status.in_(ASSIGNED), Item.information_kind.in_(("opportunity", "demand")))
    )
    backlog = db.scalars(
        unique_items(demo).where(
            *((Item.information_kind.in_(("opportunity", "demand")), *current_window(now)) if not demo else ()),
            ~Item.id.in_(select(Delivery.item_id).where(Delivery.status == "claimed"))
        )
    ).all()
    claimed_count = (
        db.scalar(
            select(func.count()).select_from(
                allocated.where(Delivery.status == "claimed").subquery()
            )
        )
        or 0
    )
    count = db.scalar(select(func.count()).select_from(allocated.subquery())) or 0
    recent = db.execute(
        allocated.add_columns(Delivery).order_by(Delivery.sent_at.desc()).limit(30)
    ).all()
    customer_rows = db.scalars(
        unique_items(demo).where(Item.information_kind == "customer_update", *current_window(now))
        .order_by(Item.created_at.desc(), Item.id).limit(30)
    ).all()
    owners = owner_names(db, [i.id for i, _ in recent] + [i.id for i in customer_rows])
    configured = all(
        (
            config.dingtalk_app_key,
            config.dingtalk_app_secret,
            config.dingtalk_robot_code,
            config.dingtalk_conversation_id,
        )
    )
    blocked = db.scalar(
        select(Delivery.status).where(Delivery.status.in_(("unknown", "failed"))).limit(1)
    )
    return {
        "pending_count": len(pending),
        "assigned_count": claimed_count,
        "pushed_count": count,
        "backlog_count": len(backlog),
        "assignment_status": "not_configured"
        if not configured
        else "paused"
        if not config.dingtalk_enabled
        else blocked or "enabled",
        "backlog_points": [
            {
                "id": i.id,
                "created_at": i.created_at,
                "waiting_hours": max(0, (now - i.created_at) / 3600),
                "fragments": len(i.fragments),
                "category": i.category,
            }
            for i in backlog
        ],
        "assigned_items": [item_record(db, i, admin, owners=owners) for i, d in recent],
        "customer_items": [item_record(db, i, admin, owners=owners) for i in customer_rows],
    }
