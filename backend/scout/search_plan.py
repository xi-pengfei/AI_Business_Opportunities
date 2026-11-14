"""Each keyword/engine pair owns its pages; empty is temporary, not exhaustion."""
import hashlib
import re
import time

from sqlalchemy import func, select, update

from scout.models import SearchCursor

RECHECK_SECONDS = 300


def variants(query):
    seeds = list(dict.fromkeys(line.strip() for line in query.splitlines() if line.strip()))
    topics = list(dict.fromkeys(re.findall(r"ERP|MES|WMS|信息化|数字化|智能体|软件定制|人工智能|AI", query, re.I)))
    tender_seeds = [s for s in seeds if re.search(r"采购|招标|投标|询价|磋商",s)]
    if not topics and not tender_seeds:
        tender_seeds = [f"{s} 采购公告" for s in seeds]
    return list(dict.fromkeys(tender_seeds + [f"{topic} {intent}" for topic in topics for intent in ("采购公告", "招标公告", "采购意向")]))


def choose(db, rule, engines, now=None, force=False):
    now = time.time() if now is None else now
    lanes = db.scalars(select(SearchCursor).where(SearchCursor.rule_id == rule.id,
                           SearchCursor.config_version == rule.version)).all()
    existing = {(c.query,c.engine) for c in lanes}
    planned = set(variants(rule.query))
    for query in sorted(planned):
        for engine in engines:
            if (query,engine) not in existing:
                lane = SearchCursor(rule_id=rule.id,config_version=rule.version,query=query,engine=engine)
                db.add(lane)
                lanes.append(lane)
    db.flush()
    eligible = [c for c in lanes if c.engine in engines and c.query in planned and (force or c.next_at <= now)]
    if not eligible:
        rule.next_run_at = min((c.next_at for c in lanes if c.engine in engines and c.query in planned), default=now+RECHECK_SECONDS)
        return None
    lane = min(eligible,key=lambda c:(c.next_at,c.last_front_at,c.query,c.engine))
    if lane.last_front_at and now-lane.last_front_at >= RECHECK_SECONDS:
        lane.page, lane.empty_streak, lane.signature = 1,0,None
    if lane.page == 1:
        lane.last_front_at = now
    return lane


def complete(db, task, results, error, now=None):
    now = time.time() if now is None else now
    ident = task.payload.get("search_cursor_id")
    lane = db.get(SearchCursor,ident) if ident else None
    if not lane:
        return
    if error:
        lane.outcome = error.code
        lane.page, lane.empty_streak = 1,0
        cooldown = 300 if error.code == "searxng_rate_limited" else 120
        # Do not hammer a challenged source by switching keywords.
        db.execute(update(SearchCursor).where(SearchCursor.engine == lane.engine).values(
            next_at=func.greatest(SearchCursor.next_at,now+cooldown)) if db.bind.dialect.name == 'postgresql' else
            update(SearchCursor).where(SearchCursor.engine == lane.engine,SearchCursor.next_at < now+cooldown).values(next_at=now+cooldown))
        lane.next_at = now+cooldown
        return
    urls = sorted({r.get('url','') for r in results})
    signature = hashlib.sha256('\n'.join(urls).encode()).hexdigest()
    repeated = bool(urls and signature == lane.signature)
    lane.empty_streak = 0 if urls else lane.empty_streak+1
    lane.outcome = 'repeated_page' if repeated else 'results' if urls else 'empty'
    if urls:
        lane.last_result_at = now
    lane.signature = signature
    if repeated or lane.empty_streak >= 2:
        lane.page, lane.empty_streak, lane.signature = 1,0,None
        lane.next_at = now+RECHECK_SECONDS
    else:
        lane.page += 1
        lane.next_at = now+3
