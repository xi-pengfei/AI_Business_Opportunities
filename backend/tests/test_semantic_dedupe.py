import json

import httpx
import pytest
from sqlalchemy import select
from test_ai_review import model_config, seed

from scout.ai_review import tick
from scout.information import item_record
from scout.models import Document, Item
from scout.semantic_dedupe import compare, shortlist


def response(result):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,
        json={"choices": [{"message": {"content": json.dumps(result)}}]})))


def test_comparison_requires_valid_target_and_two_source_quotes():
    raw = "示例工厂采购ERP项目，编号XYZ20261115。"
    candidates = [{"id": "old", "title": "ERP采购", "body": raw}]
    base = {"relation": "duplicate", "target_id": "old", "reason": "同一编号",
            "evidence_new": raw, "evidence_existing": raw}
    with response(base) as c:
        assert compare('新标题', raw, candidates, model_config(), c)['relation']=='duplicate'
    for change in ({'target_id':'invented'}, {'evidence_existing':'不存在的虚构原文证据'}):
        with response({**base, **change}) as c:
            with pytest.raises(ValueError):
                compare('新标题', raw, candidates, model_config(), c)


@pytest.mark.parametrize('relation,expected', [('duplicate','merged'),('update','active'),('uncertain','review_required'),('distinct','active')])
def test_dedupe_routes_without_deleting_evidence(database, relation, expected):
    seed(database)
    with database.begin() as db:
        original=db.get(Item,'item-0')
        original.title='示例集团ERP采购项目'
        incoming=db.get(Item,'item-1')
        incoming.title='示例集团ERP采购项目公告转载'
        incoming.source_type='social_demand'
        incoming.quality_status='review_pending'
        incoming.ai_review={}
    verdict={'decision':'buyer_demand','reason':'采购','evidence':'计划建设ERP系统。'}
    result={'relation':relation,'target_id':'item-0' if relation in ('duplicate','update') else None,'reason':'测试比对'}
    tick(model_config(),database,reviewer=lambda *args:verdict,now=946685800,deduper=lambda *args:result)
    with database() as db:
        incoming=db.get(Item,'item-1')
        assert incoming.quality_status==expected
        assert db.get(Document,incoming.document_id)
        if relation=='duplicate':
            assert incoming.related_item_id=='item-0'
            assert incoming.url in db.get(Item,'item-0').source_urls
        elif relation=='update':
            assert incoming.related_item_id=='item-0' and incoming.relation_kind=='update'


def test_shortlist_finds_cross_source_project_but_not_generic_unrelated(database):
    seed(database)
    with database.begin() as db:
        old=db.get(Item,'item-0')
        old.title='示例集团ERP采购项目'
        incoming=db.get(Item,'item-1')
        incoming.title='示例集团ERP采购项目公告'
        incoming.source_type='social_demand'
        incoming.quality_status='review_pending'
        assert [c['id'] for c in shortlist(db,incoming,'原文',946685800)]==['item-0']
        incoming.title='另一家医院的停车场系统建设'
        assert shortlist(db,incoming,'原文',946685800)==[]


@pytest.mark.parametrize('decision,kind,claim', [('buyer_demand','opportunity',True),('customer_news','customer_update',False)])
def test_monitor_routes_to_business_or_news_and_repeat_sync_preserves_it(database, decision, kind, claim):
    seed(database)
    with database.begin() as db:
        item=db.get(Item,'item-0')
        item.source_type='customer_watch'
        item.information_kind='customer_update'
        item.quality_status='review_pending'
        item.ai_review={}
    tick(model_config(),database,reviewer=lambda *args:{'decision':decision,'reason':'判断依据','evidence':'计划建设ERP系统。'},now=946685800)
    with database() as db:
        item=db.get(Item,'item-0')
        assert item.information_kind==kind and item.quality_status=='active'
        row=item_record(db,item)
        assert row['requires_claim']==claim and row['source_name']=='监控'
        assert db.scalar(select(Item).where(Item.id=='item-0')) is not None


def test_comparison_failure_does_not_repeat_successful_classification(database):
    seed(database)
    with database.begin() as db:
        item=db.get(Item,'item-0')
        item.quality_status='review_pending'
        item.ai_review={}
    calls=[]
    def classify(*args):
        calls.append('classification')
        return {'decision':'buyer_demand','reason':'需求','evidence':'计划建设ERP系统。'}
    def fail(*args):
        raise TimeoutError('must not leak')
    assert tick(model_config(),database,reviewer=classify,now=946685800,deduper=fail)=='retry_wait'
    tick(model_config(),database,reviewer=classify,now=946686800,
         deduper=lambda *args:{'relation':'distinct','target_id':None,'reason':'不同项目'})
    assert calls==['classification']
    with database() as db:
        assert db.get(Item,'item-0').quality_status=='active'
