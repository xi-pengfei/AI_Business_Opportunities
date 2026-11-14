from sqlalchemy import func, select

from scout.models import Document, Item, Task
from scout.purge_bulletins import purge


def test_delete_rejected_social_content_preserves_valid_information_and_note_dedup(database):
    with database.begin() as db:
        for number, kind in enumerate(("bulletin", "demand")):
            doc = Document(
                id=f"d{number}",
                identity=f"d{number}",
                url=f"https://example.com/{number}",
                title="招聘" if number == 0 else "找开发团队",
                raw_content="软件开发",
                content_kind="platform_note",
                content_hash=f"h{number}",
                provider="xiaohongshu",
            )
            db.add(doc)
            db.flush()
            db.add(
                Item(
                    id=f"i{number}",
                    document_id=doc.id,
                    title=doc.title,
                    url=doc.url,
                    text=doc.raw_content,
                    source_type="social_demand",
                    information_kind=kind,
                )
            )
        db.add(
            Task(
                id="bad",
                kind="ingest",
                idempotency_key="bad",
                status="succeeded",
                payload={
                    "provider": "xiaohongshu",
                    "source_type": "social_demand",
                    "note_id": "a" * 24,
                    "raw_content": "招聘软件开发",
                    "title": "招聘",
                },
                result={"item_id": "i0"},
            )
        )
    assert purge(database)["items_deleted"] == 1
    with database() as db:
        assert db.get(Item, "i1") and db.get(Document, "d1")
        assert db.get(Item, "i0") is None and db.get(Document, "d0") is None
        assert db.get(Task, "bad").payload["note_id"] == "a" * 24
        assert "raw_content" not in db.get(Task, "bad").payload
        assert db.scalar(select(func.count()).select_from(Item)) == 1
