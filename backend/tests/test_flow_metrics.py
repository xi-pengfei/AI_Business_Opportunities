from test_dingtalk import seed

from scout.flow_metrics import flow_facts, record_backlog
from scout.models import Delivery, Item


def test_backlog_records_claim_drop_and_excludes_customer(database):
    seed(database)
    with database() as db:
        db.add(
            Delivery(
                item_id="item-0",
                conversation_id="group",
                robot_code="robot",
                status="accepted",
                sent_at=900,
            )
        )
        db.commit()
        record_backlog(db, False, 1000)
        db.commit()
        record_backlog(db, False, 1001)
        delivery = db.get(Delivery, "item-0")
        delivery.status = "claimed"
        delivery.claimed_by_name = "测试成员"
        delivery.claimed_at = 1010
        other = db.get(Item, "item-1")
        other.source_type = "customer_watch"
        other.information_kind = "customer_update"
        db.commit()
        record_backlog(db, False, 1060)
        db.commit()
        facts = flow_facts(db, False, 1060, True)
        assert facts["backlog_history"] == [[960, 1, 1], [1020, 0, 0]]
        assert facts["information_sources"] == {"网络商机": 1, "客户监测": 1}
        assert any(x["target"] == "测试成员 · 已认领" for x in facts["information_flows"])
        assert "测试成员" not in str(flow_facts(db, False, 1060, False))

        assert not any(x["source"] == "客户监测" for x in facts["information_flows"])
