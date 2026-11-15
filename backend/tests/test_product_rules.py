from sqlalchemy import func, select

from scout.models import Rule, Task
from scout.product_rules import ProductSpec
from scout.search_plan import choose


def test_aliases_are_alternatives_and_actions_are_independent(client,database):
    body={'product':'MES','synonyms':'制造执行系统，制造执行管理系统\nMES','actions':['采购意向','询价公告']}
    r=client.post('/api/v1/network-rules',json=body)
    assert r.status_code==201
    saved=r.json()
    assert not saved['enabled'] and saved['name']=='MES'
    assert saved['query'].splitlines()==['MES 采购意向','MES 询价公告','制造执行系统 采购意向','制造执行系统 询价公告','制造执行管理系统 采购意向','制造执行管理系统 询价公告']
    with database() as db:
        rule=db.get(Rule,saved['id'])
        lane=choose(db,rule,['bing'],now=100)
        assert lane.query in saved['query'].splitlines()
        from scout.models import SearchCursor
        assert {x.query for x in db.scalars(select(SearchCursor)).all()}==set(saved['query'].splitlines())
    assert client.post('/api/v1/network-rules',json=body).status_code==409
    assert client.post('/api/v1/network-rules',json={**body,'product':'WMS','actions':[]}).status_code==422
    assert client.post('/api/v1/network-rules',json=body,headers={'Authorization':'Bearer test-display'}).status_code==403


def test_review_does_not_save_and_changes_take_effect_next_batch(client,database,monkeypatch):
    monkeypatch.setattr('scout.product_rules.review_product',lambda s,c:{**s.model_dump(),'queries':s.searches(),'notes':['ok'],'model':'test'})
    body={'product':'WMS','synonyms':['仓储管理系统'],'actions':['采购公告']}
    assert client.post('/api/v1/network-rules/review',json=body).status_code==200
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Rule))==0
    r=client.post('/api/v1/network-rules',json={**body,'enabled':True}).json()
    with database.begin() as db:
        from scout.service import start_rule
        task=start_rule(db,db.get(Rule,r['id']),'test',scheduled=True)
        old_query=task.payload['query']
        tid=task.id
    changed=client.patch('/api/v1/network-rules/'+r['id'],json={**body,'actions':['询价'],'enabled':True})
    assert changed.status_code==200 and changed.json()['version']==2
    assert '采购公告' not in changed.json()['query']
    with database() as db:
        assert db.get(Task,tid).payload['query']==old_query


def test_product_spec_rejects_invalid_names():
    import pytest
    from pydantic import ValidationError
    for body in ({'product':' '},{'product':'MES\nWMS'},{'product':'ERP','actions':['\n']},{'product':'ERP','synonyms':[123]}):
        with pytest.raises(ValidationError):
            ProductSpec.model_validate(body)


def test_region_cartesian_product_and_empty_scope(client,database):
    body={'product':'MES','actions':['采购公告','采购意向'],'regions':'陕西 西安，河南\n陕西'}
    result=client.post('/api/v1/network-rules',json=body).json()
    assert result['search_spec']['regions']==['陕西','西安','河南']
    expected={f'MES {a} {r}' for a in body['actions'] for r in ['陕西','西安','河南']}
    assert set(result['query'].splitlines())==expected and len(expected)==6
    with database() as db:
        from scout.models import SearchCursor
        choose(db,db.get(Rule,result['id']),['bing'],now=100)
        assert {c.query for c in db.scalars(select(SearchCursor))}==expected
    updated=client.patch('/api/v1/network-rules/'+result['id'],json={**body,'regions':'  \n '}).json()
    assert updated['search_spec']['regions']==[]
    assert updated['query'].splitlines()==['MES 采购公告','MES 采购意向']
    assert len(ProductSpec(product='MES',synonyms=['制造执行系统'],actions=body['actions'],regions=['陕西','河南','新疆']).searches())==12
    assert ProductSpec(product='MES',regions=[]).searches()==ProductSpec(product='MES').searches()


def test_ai_review_cannot_change_region_scope():
    import json

    import httpx

    from scout.config import Settings
    from scout.product_rules import review_product
    response={'product':'MES','synonyms':[],'actions':['采购公告'],'regions':['广东'],'notes':[]}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(response)}}]}))) as c:
        checked=review_product(ProductSpec(product='MES',regions=['陕西']),Settings(_env_file=None,deepseek_api_key='test'),c)
    assert checked['regions']==['陕西']
    assert checked['queries']==['MES 采购公告 陕西']
