"""Observed business backlog, never inferred from transport task counts."""

from collections import Counter

from sqlalchemy import select

from scout.display import unique_items
from scout.information import SOURCES
from scout.models import BacklogSample, Delivery, Item


def flow_facts(db, demo, now, admin):
    rows = db.execute(
        unique_items(demo).add_columns(Delivery).outerjoin(Delivery, Delivery.item_id == Item.id)
    ).all()
    sources, links = Counter(), Counter()
    for item, delivery in rows:
        source = SOURCES.get(item.source_type, item.source_type)
        sources[source] += 1
        if not delivery or delivery.status not in ("accepted", "sent", "read", "claimed"):
            continue
        if delivery and delivery.status == "claimed" and item.source_type != "customer_watch":
            target = (
                f"{delivery.claimed_by_name or '群成员'} · 已认领" if admin else "群成员 · 已认领"
            )
        elif delivery and delivery.status in ("accepted", "sent", "read"):
            target = "已播报" if item.source_type == "customer_watch" else "待认领"
        elif delivery and delivery.status in ("unknown", "restored"):
            target = "回执待核实"
        elif delivery and delivery.status == "failed":
            target = "推送失败"
        else:
            target = "待推送"
        links[(source, target)] += 1
    samples = db.scalars(
        select(BacklogSample)
        .where(BacklogSample.is_demo == demo, BacklogSample.minute >= now - 3600)
        .order_by(BacklogSample.minute)
    ).all()
    return {
        "information_sources": dict(sources),
        "information_flows": [
            {"source": s, "target": t, "value": n} for (s, t), n in links.items()
        ],
        "backlog_history": [[s.minute, s.pending, s.waiting_claim] for s in samples],
    }


def record_backlog(db, demo, now):
    from scout.retention import current_window

    minute = int(now // 60) * 60
    if db.get(BacklogSample, (minute, demo)):
        return
    rows = db.execute(
        unique_items(demo)
        .where(Item.information_kind.in_(("opportunity", "demand")), *current_window(now))
        .add_columns(Delivery)
        .outerjoin(Delivery, Delivery.item_id == Item.id)
    ).all()
    pending = waiting = 0
    for _, delivery in rows:
        if delivery and delivery.status == "claimed":
            continue
        if delivery and delivery.status in ("accepted", "sent", "read", "restored"):
            waiting += 1
        else:
            pending += 1
    db.add(BacklogSample(minute=minute, is_demo=demo, pending=pending, waiting_claim=waiting))
