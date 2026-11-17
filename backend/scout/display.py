"""Chart facts from durable records, independent of visual animation."""

import time

from sqlalchemy import and_, case, func, select

from scout.models import Document, Event, Item, Task


def public_tasks():
    return select(Task.id).where(func.coalesce(Task.payload["source_type"].as_string(), "public_tender") .in_(("public_tender", "social_demand", "customer_watch")))


def unique_items(demo):
    ranked = (
        select(
            Item.id,
            func.row_number()
            .over(partition_by=(Item.source_type, Item.url, case((Item.relation_kind.in_(("update", "distinct")), Item.id), else_="original")), order_by=(Item.created_at.asc(), Item.id))
            .label("position"),
        )
        .where(Item.is_demo == demo, Item.quality_status == "active", (Item.relation_kind.is_(None)) | (Item.relation_kind != "duplicate"),
               (Item.is_demo.is_(True)) | ((Item.source_type == "customer_watch") & (Item.information_kind == "customer_update")) | (Item.ai_review["decision"].as_string() == "buyer_demand"))
        .subquery()
    )
    return select(Item).join(ranked, Item.id == ranked.c.id).where(ranked.c.position == 1)


def chart_facts(db, demo, start):
    times = [start + i * 60 for i in range(30)]
    capture = [0] * 30
    collected = [0] * 30
    waiting = [0] * 30
    first_seen = (
        select(Item.url, func.min(Item.created_at).label("created_at"))
        .where(Item.is_demo == demo, Item.quality_status == "active")
        .group_by(Item.url)
        .subquery()
    )
    # Initial totals preserve the cumulative curve when the time window moves.
    totals = []
    for model, stamp, extra, buckets in ((Task, Task.created_at, (Task.kind == "ingest") & Task.id.in_(public_tasks()), capture),):
        totals.append(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.is_demo == demo, stamp < start, extra)
            )
            or 0
        )
        for timestamp in db.scalars(
            select(stamp).where(model.is_demo == demo, stamp >= start, extra)
        ):
            index = int((timestamp - start) // 60)
            if 0 <= index < 30:
                buckets[index] += 1
    totals.append(
        db.scalar(
            select(func.count()).select_from(first_seen).where(first_seen.c.created_at < start)
        )
        or 0
    )
    for timestamp in db.scalars(
        select(first_seen.c.created_at).where(first_seen.c.created_at >= start)
    ):
        index = int((timestamp - start) // 60)
        if 0 <= index < 30:
            collected[index] += 1
    deltas = {"task.queued": 1, "task.retry_wait": 1, "task.running": -1}
    initial = sum(
        count * deltas[kind]
        for kind, count in db.execute(
            select(Event.kind, func.count())
            .where(Event.task_id.in_(public_tasks()), Event.is_demo == demo, Event.created_at < start, Event.kind.in_(deltas))
            .group_by(Event.kind)
        )
    )
    for timestamp, kind in db.execute(
        select(Event.created_at, Event.kind).where(
            Event.task_id.in_(public_tasks()), Event.is_demo == demo, Event.created_at >= start, Event.kind.in_(deltas)
        )
    ):
        index = int((timestamp - start) // 60)
        if 0 <= index < 30:
            waiting[index] += deltas[kind]
    history = []
    for index, timestamp in enumerate(times):
        totals[0] += capture[index]
        totals[1] += collected[index]
        initial += waiting[index]
        history.append([timestamp, *totals, max(0, initial)])
    sources = db.execute(
        select(Document.provider, func.count(func.distinct(Item.url)))
        .join(Item, Item.document_id == Document.id)
        .where(Item.is_demo == demo, Item.quality_status == "active")
        .group_by(Document.provider)
    ).all()
    first = unique_items(demo).subquery()
    categories = dict(db.execute(select(first.c.category, func.count()).group_by(first.c.category)).all())
    return {"collection_history": history, "source_counts": dict(sources), "category_counts": categories}


def collector_status(db, demo, role):
    from scout.models import Rule

    now = time.time()
    rules = db.scalars(
        select(Rule).where(
            Rule.enabled.is_(True), Rule.source_type.in_(("public_tender", "social_demand", "customer_watch")), Rule.provider == "demo" if demo else Rule.provider != "demo"
        ).order_by(Rule.created_at, Rule.id)
    ).all()
    rule_ids = [r.id for r in rules]
    if not rule_ids:
        return []

    # 以下全部整批一次查询；逐规则查会做上百次全表扫（tasks 表无规则过滤时很大）。
    latest_by = {
        t.rule_id: t
        for t in db.scalars(
            select(Task)
            .where(Task.rule_id.in_(rule_ids), Task.kind == "search")
            .distinct(Task.rule_id)
            .order_by(Task.rule_id, Task.created_at.desc(), Task.id.desc())
        )
    }
    discovered = func.coalesce(Task.result["discovered"].as_integer(), 0)
    # 口径与原逐条版本一致：rounds/last_result_at 不区分 demo，last_success_at 只算本侧数据。
    stats = {
        row.rule_id: row
        for row in db.execute(
            select(
                Task.rule_id,
                func.count().label("rounds"),
                func.max(case(
                    (and_(Task.status == "succeeded", discovered > 0), Task.updated_at),
                    else_=None,
                )).label("last_result_at"),
            )
            .where(Task.rule_id.in_(rule_ids), Task.kind == "search")
            .group_by(Task.rule_id)
        )
    }
    success = {
        row.rule_id: row.last_success_at
        for row in db.execute(
            select(
                Task.rule_id,
                func.max(Task.updated_at).label("last_success_at"),
            )
            .where(Task.rule_id.in_(rule_ids), Task.kind == "search", Task.is_demo == demo, Task.status == "succeeded")
            .group_by(Task.rule_id)
        )
    }
    latest_ids = [t.id for t in latest_by.values()]
    children_by: dict[str, dict[str, int]] = {}
    if latest_ids:
        for parent_id, status, count in db.execute(
            select(Task.parent_id, Task.status, func.count())
            .where(Task.parent_id.in_(latest_ids))
            .group_by(Task.parent_id, Task.status)
        ):
            children_by.setdefault(parent_id, {})[status] = count
    duplicates_by = dict(db.execute(
        select(Task.parent_id, func.count())
        .where(Task.parent_id.in_(latest_ids), Task.result["duplicate"].as_boolean().is_(True))
        .group_by(Task.parent_id)
    ).all()) if latest_ids else {}
    opportunity_by = dict(db.execute(
        select(Task.rule_id, func.max(Item.created_at))
        .join(Item, Item.id == Task.result["item_id"].as_string())
        .where(Task.rule_id.in_(rule_ids), Item.is_demo == demo, Item.quality_status == "active",
               Item.information_kind.in_(("opportunity", "demand")))
        .group_by(Task.rule_id)
    ).all()) if rule_ids else {}

    output = []
    for rule in rules:
        latest = latest_by.get(rule.id)
        stats_row = stats.get(rule.id)
        children = children_by.get(latest.id, {}) if latest else {}
        total = sum(children.values())
        done = sum(children.get(s, 0) for s in ("succeeded", "failed", "action_required"))
        state = latest.status if latest else "queued"
        if state == "succeeded":
            state = "cleaning" if done < total else "next_batch"
        output.append(
            {
                "id": rule.id,
                "name": rule.name if role == "admin" else "采集规则",
                "query": latest.payload.get("query", "") if latest and role == "admin" else "",
                "state": state,
                "provider": rule.provider,
                "last_success_at": success.get(rule.id),
                "next_action_at": latest.available_at if latest and state == "retry_wait" else rule.next_run_at,
                "error_code": latest.error_code if latest else None,
                "next_run_at": rule.next_run_at,
                "continuous": rule.interval_seconds == 0,
                "search_page": latest.payload.get("page",1) if latest else 1,
                "search_engine": latest.result.get("search_engine") or latest.payload.get("engine", "") or ("xiaohongshu" if rule.provider == "xiaohongshu" else "") if latest else "",
                "search_outcome": latest.error_code or latest.result.get("search_outcome", "") if latest else "",
                "last_result_at": stats_row.last_result_at if stats_row else None,
                "last_opportunity_at": opportunity_by.get(rule.id),
                "waiting_recheck": state in ("next_batch", "failed") and rule.next_run_at > time.time()+5,

                "done": done,
                "total": total,
                "duplicates": duplicates_by.get(latest.id, 0) if latest else 0,
                "rounds": stats_row.rounds if stats_row else 0,
                "max_results": rule.max_results,
            }
        )
    from scout.collector_history import collector_history
    histories = collector_history(db, [row["id"] for row in output], demo, now)
    for row in output:
        row["history"] = histories[row["id"]]
    return output


def discovery_facts(db, demo, now):
    """Count first URL appearances, using Shanghai civil days, not browser timezone."""
    from datetime import datetime, timedelta, timezone

    zone = timezone(timedelta(hours=8))
    today = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = int((today - timedelta(days=89)).timestamp())
    minute_start = int(now // 60) * 60 - 29 * 60
    first = unique_items(demo).subquery()
    minute = func.floor((first.c.created_at - minute_start) / 60)
    grouped = db.execute(
        select(minute, Document.provider, func.count())
        .select_from(first).join(Document, Document.id == first.c.document_id)
        .where(first.c.created_at >= minute_start, first.c.created_at <= now)
        .group_by(minute, Document.provider)
    ).all()
    growth = [{"start": minute_start + i * 60, "end": minute_start + (i + 1) * 60,
               "sources": {}} for i in range(30)]
    for index, provider, count in grouped:
        if 0 <= int(index) < 30:
            growth[int(index)]["sources"][provider] = count
    day = func.floor((first.c.created_at - day_start) / 86400)
    counts = dict(db.execute(
        select(day, func.count()).select_from(first)
        .where(first.c.created_at >= day_start, first.c.created_at <= now).group_by(day)
    ).all())
    calendar = []
    for i in range(90):
        stamp = day_start + i * 86400
        calendar.append({"date": datetime.fromtimestamp(stamp, zone).date().isoformat(),
                         "start": stamp, "end": stamp + 86400, "count": counts.get(i, 0)})
    return {"discovery_history": growth, "discovery_calendar": calendar}
