from datetime import datetime, timedelta

from sqlalchemy import select

from scout.models import Delivery, Document, Item
from scout.quality import describe
from scout.reprocess import reprocess
from scout.retention import archive_expired

NOW = datetime.fromisoformat("2026-11-15T12:00:00+08:00")


def test_date_window_boundaries_and_policy_routing():
    def quality(day, title="甲公司软件采购公告", raw="甲公司拟采购ERP系统。"):
        return describe(title, raw, day, now=NOW)
    assert quality("2026-10-16")["quality_status"] == "active"
    assert quality("2026-10-15")["quality_reason"] == "outside_30_days"
    assert quality("2026-11-16")["quality_reason"] == "future_publication"
    assert quality(None)["quality_reason"] == "unverified_date"
    assert quality("2026-11-15")["information_kind"] == "opportunity"
    assert quality("2026-11-15", "关于企业数字化的指导意见")["information_kind"] == "bulletin"
    assert quality("2026-11-15", "医院信息系统采购公告", "某医院拟采购ERP系统。")["information_kind"] == "opportunity"
    assert quality("2026-11-15", "甲公司招聘工程师")["information_kind"] == "bulletin"
    assert quality("2026-11-15", "某委员会关于印发人工智能实施意见", "推动企业建设协同设计系统。")["information_kind"] == "bulletin"
    assert quality("2026-11-15", "甲招标采购公司", "招标采购信息，招标采购公告。")["information_kind"] == "bulletin"
    assert quality("2026-11-15", "甲公司ERP采购异常")["information_kind"] == "bulletin"


def add(db, ident, captured, published="2026-11-14", content=None):
    doc = Document(identity=ident, url=f"https://example.com/{ident}", title="甲公司软件采购公告",
                   raw_content=content or f"甲公司拟采购ERP系统，项目编号{ident}。", content_kind="search_excerpt",
                   content_hash=content or ident, provider="test", published_at=published)
    db.add(doc)
    db.flush()
    item = Item(id=ident, document_id=doc.id, title=doc.title, url=doc.url, text=doc.raw_content,
                created_at=captured, published_at=published, information_kind="opportunity")
    db.add(item)
    db.flush()
    return item


def test_expiry_preserves_claim_and_raw_evidence_and_is_idempotent(database):
    stamp = NOW.timestamp()
    with database.begin() as db:
        add(db, "unhandled", stamp - 30 * 86400)
        add(db, "claimed", stamp - 31 * 86400)
        add(db, "stale", stamp, "2026-10-15")
        add(db, "fresh", stamp)
        db.add(Delivery(item_id="claimed", conversation_id="test", robot_code="test", status="claimed", claimed_by_name="张三"))
    assert archive_expired(database, stamp) == 2
    assert archive_expired(database, stamp) == 0
    with database() as db:
        assert db.get(Item, "unhandled").quality_reason == "unhandled_30_days"
        assert db.get(Item, "claimed").quality_status == "active"
        assert db.get(Item, "fresh").quality_status == "active"
        assert db.get(Delivery, "claimed").claimed_by_name == "张三"
        assert len(db.scalars(select(Document)).all()) == 4


def test_historical_reprocessing_deduplicates_without_refreshing_age(database):
    stamp = NOW.timestamp()
    with database.begin() as db:
        add(db, "first", stamp - 20, content="甲公司拟采购ERP系统。")
        add(db, "copy", stamp - 10, content="甲公司拟采购ERP系统。")
        add(db, "old", stamp - 31 * 86400)
        add(db, "unknown", stamp, None)
    first = reprocess(database, stamp)
    assert first == reprocess(database, stamp)
    assert first["duplicate_information"] == 1
    assert first["unverified_date"] == 1
    assert first["unhandled_30_days"] == 1
    with database() as db:
        assert db.get(Item, "first").created_at == stamp - 20
        assert len(db.scalars(select(Document)).all()) == 4
    assert archive_expired(database, (NOW + timedelta(days=31)).timestamp()) == 1
