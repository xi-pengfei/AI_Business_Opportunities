"""Business backlog counts only undistributed items; transport queues are separate."""

from sqlalchemy import func, select

from scout.models import Delivery, Item

ASSIGNED = ("accepted", "sent", "read", "claimed")


def pending_items(demo=False, now=None):
    from scout.display import unique_items
    from scout.retention import current_window

    return unique_items(demo).where(
        *((Item.information_kind == "opportunity", *current_window(now)) if not demo else ()),
        ~Item.id.in_(select(Delivery.item_id).where(Delivery.status.in_(ASSIGNED)))
    )


def assignment_facts(db, demo, now, admin):
    from scout.config import settings
    from scout.display import unique_items
    from scout.retention import current_window

    config = settings()
    pending = db.scalars(pending_items(demo, now)).all()
    allocated = (
        select(Item).where(Item.is_demo == demo)
        .join(Delivery, Delivery.item_id == Item.id)
        .where(Delivery.status.in_(ASSIGNED))
    )
    backlog = db.scalars(
        unique_items(demo).where(
            *((Item.information_kind == "opportunity", *current_window(now)) if not demo else ()),
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
        "assigned_items": [
            {
                "id": i.id,
                "title": i.title if admin else "已分配信息",
                "created_at": i.created_at,
                "is_demo": i.is_demo,
                "recipient": d.recipient if admin else "钉钉群",
                "delivery_status": d.status,
                "sent_at": d.sent_at,
                "read_at": d.read_at,
                "claimed_by": d.claimed_by_name if admin else "群成员",
                "claimed_at": d.claimed_at,
            }
            for i, d in recent
        ],
    }
