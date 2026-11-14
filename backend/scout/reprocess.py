"""Idempotent evidence cleanup. Preserve original documents and delivery history."""
import time
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from scout.db import Session
from scout.models import Delivery, Document, Item
from scout.policies import describe_public_tender, describe_social_demand
from scout.providers import canonical_url
from scout.quality import ZONE


def reprocess(sessions=Session, now=None):
    now = time.time() if now is None else now
    counts = Counter()
    urls, hashes = set(), set()
    with sessions.begin() as db:
        claimed = set(db.scalars(select(Delivery.item_id).where(Delivery.status == "claimed")))
        rows = db.execute(select(Item, Document).join(Document, Item.document_id == Document.id)
                          .where(Item.is_demo.is_(False)).order_by(Item.created_at, Item.id))
        for item, doc in rows:
            policy = describe_social_demand if item.source_type == "social_demand" else describe_public_tender
            result = policy(doc.title, doc.raw_content, doc.published_at, datetime.fromtimestamp(now, ZONE))
            url = canonical_url(doc.url)
            if url in urls or doc.content_hash in hashes:
                result.update(quality_status="archived", quality_reason="duplicate_information")
            elif item.id not in claimed and item.created_at <= now - 30 * 86400:
                result.update(quality_status="archived", quality_reason="unhandled_30_days")
            urls.add(url)
            hashes.add(doc.content_hash)
            for key, value in result.items():
                setattr(item, key, value)
            item.url = url
            counts[result["quality_reason"] or result["information_kind"]] += 1
    return dict(counts)


def main():
    print(reprocess())


if __name__ == "__main__":
    main()
