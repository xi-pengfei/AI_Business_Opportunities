"""Read-only search execution history; returned hits are not accepted opportunities."""
from sqlalchemy import select

from scout.models import Event, Task


def collector_history(db, rule_ids, demo, now):
    start = int(now // 150) * 150 - 23 * 150
    history = {rid: [dict(start=start + i * 150, results=None, successes=0,
                          failures=0, warnings=0, running=0) for i in range(24)]
               for rid in rule_ids}
    if not rule_ids:
        return history
    rows = db.execute(select(Event, Task.rule_id, Task.result).join(Task, Task.id == Event.task_id).where(
        Task.rule_id.in_(rule_ids), Task.kind == "search", Task.is_demo == demo,
        Event.is_demo == demo, Event.created_at >= start, Event.created_at <= now,
        Event.kind.in_(("task.running", "task.succeeded", "task.failed", "task.retry_wait", "task.action_required")),
    ).order_by(Event.created_at, Event.id))
    seen_success = set()
    for event, rule_id, result in rows:
        bucket = history[rule_id][int((event.created_at - start) // 150)]
        if event.kind == "task.succeeded":
            if event.task_id in seen_success:
                continue
            seen_success.add(event.task_id)
            bucket["successes"] += 1
            count = result.get("discovered")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                bucket["results"] = (bucket["results"] or 0) + count
            if result.get("search_outcome") == "partial_results":
                bucket["warnings"] += 1
        elif event.kind == "task.running":
            bucket["running"] += 1
        else:
            code = event.data.get("error_code") or ""
            warning = event.kind == "task.action_required" or any(x in code for x in ("rate_limited", "verification", "authorization", "login_required"))
            bucket["warnings" if warning else "failures"] += 1
    return history
