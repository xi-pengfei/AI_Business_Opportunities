"""Delete undelivered bulletin content; never delete delivery or claim history."""
import hashlib
from collections import Counter

from sqlalchemy import select

from scout.db import Session
from scout.models import Delivery, Document, Item, RemovedEvidence, Task
from scout.policies import describe_public_tender
from scout.providers import canonical_url, clean_text


def discarded_payload(provider, reason="not_opportunity"):
    return {"provider": provider, "discarded": reason}


def purge(sessions=Session):
    counts = Counter()
    with sessions.begin() as db:
        delivered = set(db.scalars(select(Delivery.item_id)))
        removed_ids = set()
        for item in db.scalars(select(Item).where(Item.is_demo.is_(False))).all():
            if item.information_kind != "bulletin" or item.id in delivered:
                continue
            doc = db.get(Document, item.document_id)
            key = hashlib.sha256(canonical_url(doc.url).encode()).hexdigest()
            db.merge(RemovedEvidence(url_hash=key, content_hash=doc.content_hash))
            removed_ids.add(item.id)
            db.delete(item)
            db.flush()
            db.delete(doc)
            counts["items_deleted"] += 1
        # Remove source copies from completed task payloads, too.
        hashes = set(db.scalars(select(RemovedEvidence.content_hash)))
        for task in db.scalars(select(Task).where(Task.is_demo.is_(False), Task.kind == "ingest",
                                                 Task.status.in_(("succeeded", "failed", "action_required")))).all():
            p = task.payload
            if p.get("source_type", "public_tender") != "public_tender":
                continue
            raw = p.get("raw_content")
            if not raw or task.result.get("item_id") in delivered:
                continue
            removed = task.result.get("item_id") in removed_ids or hashlib.sha256(clean_text(raw).encode()).hexdigest() in hashes
            bulletin = describe_public_tender(p.get("title", ""), raw, p.get("published_at"))["information_kind"] == "bulletin"
            if removed or bulletin:
                task.payload = discarded_payload(p.get("provider"), "removed_information")
                task.result = {"discarded": True, "reason": "removed_information"}
                task.status = "succeeded"
                counts["payloads_removed"] += 1
    return dict(counts)


if __name__ == "__main__":
    print(purge())
