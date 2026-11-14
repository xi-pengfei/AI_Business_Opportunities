from sqlalchemy import func, select

from scout.models import Delivery, DeliveryGate, Document, Item, RemovedEvidence, Task
from scout.purge_bulletins import purge
from scout.service import enqueue, save_item


def test_bulletin_is_discarded_without_content_storage(database):
    with database.begin() as db:
        task = enqueue(db, kind="ingest", key="bulletin", payload={
            "provider": "searxng", "title": "企业数字化政策解读", "url": "https://example.com/policy",
            "raw_content": "关于印发企业数字化建设指导意见。", "content_kind": "search_excerpt"})
        assert save_item(db, task) == {"discarded": True, "reason": "not_opportunity"}
        assert "raw_content" not in task.payload
        assert db.scalar(select(func.count()).select_from(Item)) == 0
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_purge_preserves_deliveries_and_gate_but_removes_bulletins(database):
    from test_retention import NOW, add

    with database.begin() as db:
        item = add(db, "claimed", NOW.timestamp())
        bulletin = add(db, "bulletin", NOW.timestamp())
        bulletin.information_kind = "bulletin"
        add(db, "pending", NOW.timestamp())
        db.add(Delivery(item_id=item.id, conversation_id="group", robot_code="robot", status="claimed", claimed_by_name="张三"))
        db.add(DeliveryGate(id="dingtalk", current_item_id=item.id))
        task = enqueue(db, kind="ingest", key="previous", payload={
            "provider": "searxng", "title": item.title, "url": item.url,
            "raw_content": item.text, "content_kind": "search_excerpt"})
        task.status = "succeeded"
        task.result = {"item_id": item.id}
    result = purge(database)
    assert result["items_deleted"] == 1
    with database.begin() as db:
        assert db.scalar(select(func.count()).select_from(Delivery)) == 1
        assert db.scalar(select(func.count()).select_from(Document)) == 2
        assert db.scalar(select(func.count()).select_from(RemovedEvidence)) == 1
        assert db.get(DeliveryGate, "dingtalk").current_item_id == "claimed"
        assert "raw_content" in db.scalar(select(Task)).payload
        task = enqueue(db, kind="ingest", key="repeated", payload={
            "provider": "searxng", "title": "甲公司软件采购公告", "url": "https://example.com/bulletin",
            "raw_content": "甲公司拟采购ERP系统，更新后的搜索摘要。", "content_kind": "search_excerpt"})
        assert save_item(db, task)["reason"] == "removed_information"
        assert db.scalar(select(func.count()).select_from(Item)) == 2
    assert purge(database).get("items_deleted", 0) == 0
