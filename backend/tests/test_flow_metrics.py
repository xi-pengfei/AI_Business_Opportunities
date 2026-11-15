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
        assert facts["information_sources"] == {}  # No enabled collection rules in this fixture.
        assert any(x["target"] == "测试成员 · 已认领" for x in facts["information_flows"])
        assert "测试成员" not in str(flow_facts(db, False, 1060, False))

        assert not any(x["source"] == "监控" for x in facts["information_flows"])


def test_hit_rate_uses_finished_searches_not_items_or_retry_attempts(database):
    from scout.flow_metrics import search_hit_facts
    from scout.models import Task
    with database.begin() as db:
        for i, (kind, status, discovered) in enumerate([
            ('search', 'succeeded', 8), ('search', 'succeeded', 0),
            ('search', 'failed', 0), ('search', 'running', 0), ('ingest', 'succeeded', 1),
        ]):
            db.add(Task(kind=kind, status=status, result={'discovered': discovered},
                        payload={}, idempotency_key=f'hit-{i}', updated_at=1000, is_demo=False))
    with database() as db:
        facts = search_hit_facts(db, False, 1100)
        assert facts['search_hit_total'] == 3
        assert facts['search_hit_success'] == 1
        assert facts['search_hit_history'] == [[900, 3, 1, 1]]
        assert search_hit_facts(db, False, 5000)['search_hit_history'] == []


def test_source_distribution_uses_enabled_product_and_nonzero_only(database):
    from scout.models import Rule, Task
    seed(database)
    with database.begin() as db:
        for ident,name,enabled in [('mes','MES',True),('erp','ERP',True),('zero','智能文档处理',True)]:
            db.add(Rule(id=ident,name=name,query=name,provider='searxng',enabled=enabled,source_type='public_tender',search_spec={'product':name}))
        db.flush()
        for i,rid in enumerate(['mes','erp']):
            db.add(Task(kind='ingest',status='succeeded',rule_id=rid,payload={},result={'item_id':f'item-{i}','duplicate':False},idempotency_key=f'origin{i}',created_at=100+i))
        db.add(Task(kind='ingest',status='succeeded',rule_id='erp',payload={},result={'item_id':'item-0','duplicate':True},idempotency_key='duplicate',created_at=200))
    with database.begin() as db:
        assert flow_facts(db,False,1000,True)['information_sources']=={'ERP':1,'MES':1}
        db.get(Rule,'mes').enabled=False
    with database.begin() as db:
        assert flow_facts(db,False,1000,True)['information_sources']=={'ERP':1}
        db.get(Rule,'mes').enabled=True
        db.get(Item,'item-1').quality_status='review_pending'
    with database() as db:
        assert flow_facts(db,False,1000,True)['information_sources']=={'MES':1}


def test_social_and_customer_source_disappear_when_stopped(database):
    from scout.models import Rule, Task
    seed(database)
    with database.begin() as db:
        db.get(Item,'item-0').source_type='social_demand'
        db.get(Item,'item-1').source_type='customer_watch'
        db.get(Item,'item-1').information_kind='customer_update'
        db.add_all([Rule(id='social',name='需求',query='ERP',source_type='social_demand',provider='xiaohongshu',enabled=True),
                    Rule(id='watch',name='客户',query='客户',source_type='customer_watch',provider='searxng',enabled=True)])
        db.flush()
        db.add(Task(kind='ingest',status='succeeded',rule_id='watch',payload={},result={'item_id':'item-1'},idempotency_key='watch-origin'))
    with database.begin() as db:
        assert flow_facts(db,False,1000,True)['information_sources']=={'客户监控':1,'小红书':1}
        db.get(Rule,'social').enabled=False
        db.get(Rule,'watch').enabled=False
    with database() as db:
        assert flow_facts(db,False,1000,True)['information_sources']=={}
