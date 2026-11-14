"""Idempotent evidence cleanup. Preserve original documents and task history."""
from collections import Counter

from sqlalchemy import select

from scout.db import Session
from scout.models import Document, Item
from scout.quality import describe


def main():
    counts = Counter()
    with Session.begin() as db:
        for item, doc in db.execute(select(Item, Document).join(Document, Item.document_id == Document.id).where(Item.is_demo.is_(False))):
            result = describe(doc.title, doc.raw_content, doc.published_at)
            for key, value in result.items():
                setattr(item, key, value)
            counts[result["quality_reason"] or "active"] += 1
    print(dict(counts))


if __name__ == "__main__":
    main()
