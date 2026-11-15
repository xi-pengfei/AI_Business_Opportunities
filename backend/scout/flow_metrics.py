"""Observed business backlog, never inferred from transport task counts."""

from collections import Counter

from sqlalchemy import select

from scout.display import unique_items
from scout.information import SOURCES
from scout.models import BacklogSample, CustomerSignal, Delivery, Item, Rule, Task


def flow_facts(db, demo, now, admin):
    rows = db.execute(
        unique_items(demo).add_columns(Delivery).outerjoin(Delivery, Delivery.item_id == Item.id)
    ).all()
    sources = active_source_counts(db, demo, [item for item, _ in rows])
    links = Counter()
    for item, delivery in rows:
        source = SOURCES.get(item.source_type, item.source_type)
        if not delivery or delivery.status not in ("accepted", "sent", "read", "claimed"):
            continue
        if delivery and delivery.status == "claimed" and item.information_kind != "customer_update":
            target = (
                f"{delivery.claimed_by_name or '群成员'} · 已认领" if admin else "群成员 · 已认领"
            )
        elif delivery and delivery.status in ("accepted", "sent", "read"):
            target = "已播报" if item.information_kind == "customer_update" else "待认领"
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
        **search_hit_facts(db, demo, now),
    }


def active_source_counts(db, demo, items):
    """Only enabled sources with approved information; each item has one origin."""
    rules={r.id:r for r in db.scalars(select(Rule).where(Rule.enabled.is_(True)))}
    items={i.id:i for i in items}  # Delivery joins must never multiply counts.
    if not items or not rules:
        return {}
    origins={}
    # Use the original successful ingest, not subsequent duplicate discoveries.
    tasks=db.scalars(select(Task).where(
        Task.is_demo==demo, Task.kind=='ingest', Task.status=='succeeded',
        Task.result['item_id'].as_string().in_(items),
        (Task.result['duplicate'].as_boolean().is_(False)) | (Task.result['duplicate'].as_boolean().is_(None)),
    ).order_by(Task.created_at,Task.id))
    for task in tasks:
        origins.setdefault(task.result['item_id'],task.rule_id)
    watched={r.customer_id for r in rules.values() if r.source_type=='customer_watch'}
    monitored_ids=set(db.scalars(select(CustomerSignal.id).where(
        CustomerSignal.id.in_(items), CustomerSignal.customer_id.in_(watched)))) if watched else set()
    social_enabled=any(r.source_type=='social_demand' for r in rules.values())
    counts=Counter()
    for item in items.values():
        if item.source_type=='social_demand':
            if social_enabled:
                counts['小红书']+=1
        elif item.source_type=='customer_watch':
            rule=rules.get(origins.get(item.id))
            if item.id in monitored_ids or (rule and rule.source_type=='customer_watch'):
                counts['客户监控']+=1
        elif item.source_type=='public_tender':
            rule=rules.get(origins.get(item.id))
            if rule and rule.source_type=='public_tender' and (rule.search_spec or {}).get('product') and not rule.search_spec.get('retired'):
                name=rule.name if rule.name not in ('小红书','客户监控') else rule.name+'（网络商机）'
                counts[name]+=1
    return dict(sorted(counts.items(),key=lambda row:(-row[1],row[0])))


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


def search_hit_facts(db, demo, now):
    # One completed logical search (including exhausted failures) is one query, not each HTTP retry.
    rows = db.execute(select(Task.updated_at, Task.status, Task.result).where(
        Task.is_demo == demo, Task.kind == "search", Task.updated_at >= now - 3600,
        Task.updated_at <= now, Task.status.in_(("succeeded", "failed", "action_required")),
    )).all()
    buckets = {}
    for stamp, status, result in rows:
        slot = int(stamp // 300) * 300
        row = buckets.setdefault(slot, [slot, 0, 0, 0])
        row[1] += 1
        row[2] += int(status == "succeeded" and (result or {}).get("discovered", 0) > 0)
        row[3] += int(status != "succeeded")
    history = sorted(buckets.values())
    total = sum(r[1] for r in history)
    hits = sum(r[2] for r in history)
    return {"search_hit_history": history, "search_hit_total": total, "search_hit_success": hits}
