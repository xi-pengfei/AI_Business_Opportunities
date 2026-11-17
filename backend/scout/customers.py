"""Customer-only evidence. Public rejection fingerprints and deliveries do not apply."""
import hashlib
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy import text as sql_text

from scout.models import Customer, CustomerSignal, Document, Rule, Task, User
from scout.providers import ProviderError, canonical_url, clean_text
from scout.quality import ZONE, describe

TOPICS = (
    ("招采", r"采购|招标|询价|磋商|投标"),
    ("扩产与建设", r"扩产|产能|扩建|投产|厂房|生产基地|新建产线"),
    ("信息化与智能制造", r"信息化|数字化|数智|智能制造|智改数转|人工智能|智能体|ERP|MES|WMS|DCS|工业软件|自动化|数据平台"),
)


def queries(customer):
    names = list(dict.fromkeys([customer.name, *customer.aliases]))
    # Bare exact names find news without guessing how a publisher describes it.
    seeds = [f'"{n}"' for n in names]
    short = customer.aliases[0] if customer.aliases else customer.name
    seeds += [f'"{short}" {topic}' for topic in ("采购 招标", "扩产 产能", "信息化 智能制造")]
    for url in getattr(customer, 'reference_urls', []) or []:
        host = urlsplit(url).hostname
        if host:
            seeds.append(f'"{short}" site:{host}')
    return "\n".join(dict.fromkeys(seeds))


def signal_window(now=None):
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, ZONE).date()
    return (CustomerSignal.quality_status == "active",
            CustomerSignal.published_at >= (today - timedelta(days=30)).isoformat(),
            CustomerSignal.published_at <= today.isoformat(),
            CustomerSignal.created_at > now - 30 * 86400)


def classify(customer, title, raw, published_at=None):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    evidence = title + " " + soup.get_text(" ", strip=True)
    # 身份只认名称/其他叫法命中正文；参考网址只影响搜索词，不代表客户身份。
    matched = next((n for n in [customer.name, *customer.aliases] if n in evidence), None)
    if not matched:
        return None, "customer_mismatch"
    topic = next((label for label, pattern in TOPICS if re.search(pattern, evidence, re.I)), None)
    if not topic:
        return None, "outside_customer_topics"
    quality = describe(title, raw, published_at)
    return {**quality, "matched_name": matched, "topic": topic}, None


def save_signal(db, task):
    from scout.information import sync_customer_item
    from scout.service import emit

    p = task.payload
    customer = db.get(Customer, p.get("customer_id"))
    if not customer:
        raise ProviderError("customer_missing", True)
    url = canonical_url(p["url"])
    raw = p["raw_content"]
    normalized = clean_text(raw)
    if not normalized:
        raise ProviderError("empty_content")
    from types import SimpleNamespace
    identity = SimpleNamespace(**p["customer_snapshot"]) if p.get("customer_snapshot") else customer
    quality, reason = classify(identity, p["title"], raw, p.get("published_at"))
    if reason:
        emit(db, task, "customer.discarded", customer_id=customer.id, reason=reason)
        return {"discarded": True, "reason": reason}
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
    # Serialize one customer's writes; URL and mirrored-content uniqueness survive retries.
    if db.bind.dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(f"customer:{customer.id}".encode()).digest()[:8], "big", signed=True)
        db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    existing = db.scalar(select(CustomerSignal).where(CustomerSignal.customer_id == customer.id,
        (CustomerSignal.url == url) | (CustomerSignal.content_hash == fingerprint)).limit(1))
    if existing and not (existing.quality_reason == "unverified_date" and existing.content_hash == fingerprint and quality["quality_status"] == "active"):
        item = sync_customer_item(db, existing)
        item.source_urls = list(dict.fromkeys([item.url, *item.source_urls, url]))
        emit(db, task, "customer.duplicate", customer_id=customer.id, signal_id=existing.id)
        return {"signal_id": existing.id, "duplicate": True}
    # Evidence namespace intentionally differs from public tender's URL identity.
    # Public cleanup cannot delete or blacklist a customer's news evidence.
    identity = hashlib.sha256(f"customer:{customer.id}|{url}|{fingerprint}|{quality['published_at']}".encode()).hexdigest()
    doc = Document(identity=identity, url=url, title=p["title"], raw_content=raw,
                   content_kind=p["content_kind"], content_hash=fingerprint,
                   provider=p["provider"], published_at=p.get("published_at"), is_demo=False)
    db.add(doc)
    db.flush()
    if existing:
        existing.document_id = doc.id
        existing.published_at = quality["published_at"]
        existing.quality_status = "active"
        existing.quality_reason = None
        existing.fragments = quality["fragments"]
        existing.created_at = time.time()
        sync_customer_item(db, existing)
        emit(db, task, "item.filtered", item_id=existing.id, reason="ai_review_required")
        emit(db, task, "customer.created", customer_id=customer.id, signal_id=existing.id, date_verified=True)
        return {"signal_id": existing.id, "duplicate": False, "quality_status": "active"}
    signal = CustomerSignal(customer_id=customer.id, document_id=doc.id, url=url,
        content_hash=fingerprint, topic=quality["topic"], matched_name=quality["matched_name"],
        fragments=quality["fragments"], published_at=quality["published_at"],
        quality_status=quality["quality_status"], quality_reason=quality["quality_reason"])
    db.add(signal)
    db.flush()
    sync_customer_item(db, signal)
    # Visible publication is emitted after AI routes news versus demand.
    emit(db, task, "customer.created" if signal.quality_status == "active" else "customer.filtered",
         customer_id=customer.id, signal_id=signal.id)
    return {"signal_id": signal.id, "duplicate": False, "quality_status": signal.quality_status}


def customer_records(db):
    counts = dict(db.execute(select(CustomerSignal.customer_id, func.count()).where(
        *signal_window()).group_by(CustomerSignal.customer_id)).all())
    output = []
    for customer, rule, owner in db.execute(
        select(Customer, Rule, User).join(Rule, Rule.customer_id == Customer.id)
        .outerjoin(User, User.id == Rule.owner_user_id).order_by(Customer.created_at)):
        latest = db.scalar(select(Task).where(Task.rule_id == rule.id, Task.kind == "search").order_by(Task.created_at.desc()).limit(1))
        newest = db.scalar(select(CustomerSignal).where(CustomerSignal.customer_id == customer.id,
            *signal_window()).order_by(CustomerSignal.created_at.desc()).limit(1))
        output.append({"id": customer.id, "name": customer.name, "aliases": customer.aliases,
            "reference_urls": customer.reference_urls,
            "rule_id": rule.id, "enabled": rule.enabled,
            "query": latest.payload.get("query") if latest else None,
            "state": latest.status if latest else "queued",
            "error_code": latest.error_code if latest else None,
            "last_search_at": latest.updated_at if latest else None,
            "last_found_at": newest.created_at if newest else None,
            "signal_count": counts.get(customer.id, 0),
            "owner_user_id": rule.owner_user_id,
            "owner_name": (owner.display_name or owner.username) if owner is not None else None,
            "next_run_at": rule.next_run_at})
    return output
