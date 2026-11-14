"""Chart facts from durable records, independent of visual animation."""

from sqlalchemy import func, select

from scout.models import Document, Event, Item, Task


def chart_facts(db, demo, start):
    times = [start + i * 60 for i in range(30)]
    capture = [0] * 30
    collected = [0] * 30
    waiting = [0] * 30
    # Initial totals preserve the cumulative curve when the time window moves.
    totals = []
    for model, stamp, extra, buckets in (
        (Task, Task.created_at, Task.kind == "ingest", capture),
        (Item, Item.created_at, True, collected),
    ):
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
    deltas = {"task.queued": 1, "task.retry_wait": 1, "task.running": -1}
    initial = sum(
        count * deltas[kind]
        for kind, count in db.execute(
            select(Event.kind, func.count())
            .where(Event.is_demo == demo, Event.created_at < start, Event.kind.in_(deltas))
            .group_by(Event.kind)
        )
    )
    for timestamp, kind in db.execute(
        select(Event.created_at, Event.kind).where(
            Event.is_demo == demo, Event.created_at >= start, Event.kind.in_(deltas)
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
        select(Document.provider, func.count())
        .join(Item, Item.document_id == Document.id)
        .where(Item.is_demo == demo)
        .group_by(Document.provider)
    ).all()
    return {"collection_history": history, "source_counts": dict(sources)}
