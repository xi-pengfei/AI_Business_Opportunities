import hashlib
from datetime import datetime, timedelta

from sqlalchemy import func, select

from scout import service
from scout.customers import classify
from scout.models import (
    Customer,
    CustomerSignal,
    Delivery,
    Document,
    Item,
    RemovedEvidence,
    Rule,
    Task,
)
from scout.quality import ZONE
from scout.retention import archive_expired
from scout.search_plan import choose


def customer(client):
    r = client.post('/api/v1/customers', json={'name':'示例光电股份有限公司','aliases':['示例光电']})
    assert r.status_code == 201
    return r.json()


def ingest(db, customer_id, url='https://example.com/news/1', published=None):
    p = {'source_type':'customer_watch','customer_id':customer_id,'provider':'searxng',
         'url':url,'title':'示例光电新建智能制造生产基地',
         'raw_content':'示例光电股份有限公司新建智能制造生产基地，将扩大产能并建设MES数字化系统。',
         'published_at':published or datetime.now(ZONE).date().isoformat(), 'content_kind':'search_excerpt'}
    task = service.enqueue(db,kind='ingest',payload=p,key=url+str(published))
    return service.save_item(db,task), task


def test_customer_signal_joins_library_without_claim_backlog(client, database):
    c = customer(client)
    assert client.get('/api/v1/rules').json() == []
    with database.begin() as db:
        db.add(RemovedEvidence(url_hash=hashlib.sha256(b'https://example.com/news/1').hexdigest(),content_hash='ignored'))
        result, _ = ingest(db,c['id'])
        assert result['quality_status'] == 'active'
        duplicate, _ = ingest(db,c['id'],url='https://example.com/mirror')
        assert duplicate['duplicate']
        assert db.scalar(select(func.count()).select_from(CustomerSignal)) == 1
        assert db.scalar(select(func.count()).select_from(Item)) == 1
        assert db.scalar(select(func.count()).select_from(Delivery)) == 0
    rows=client.get('/api/v1/customer-signals').json()
    assert rows['total']==1 and rows['items'][0]['matched_name']=='示例光电股份有限公司'
    assert client.get('/api/v1/display/snapshot').json()['item_count']==0
    from scout.ai_review import tick
    from scout.config import Settings
    tick(Settings(_env_file=None,deepseek_api_key='test-key'),database,
         reviewer=lambda *args: {'decision':'customer_news','reason':'扩产新闻，无明确采购','evidence':''})
    snap=client.get('/api/v1/display/snapshot').json()
    assert snap['item_count']==1 and snap['collectors']==[]
    assert snap['pending_count']==0 and snap['backlog_count']==0
    assert snap['customer_items'][0]['source_name']=='监控'
    assert snap['customer_items'][0]['requires_claim'] is False
    assert client.get('/api/v1/items').json()[0]['source_type']=='customer_watch'
    masked=client.get('/api/v1/customer-signals',headers={'Authorization':'Bearer test-display'}).json()
    assert '示例' not in str(masked) and 'url' not in masked['items'][0]
    assert client.get('/api/v1/customers',headers={'Authorization':'Bearer test-display'}).status_code==403


def test_identity_topic_and_date_admission(client, database):
    c=customer(client)
    with database.begin() as db:
        target=db.get(Customer,c['id'])
        assert classify(target,'另一家公司扩产','另一家公司智能制造扩产')[1]=='customer_mismatch'
        assert classify(target,'示例光电周年庆','示例光电举办周年庆典')[1]=='outside_customer_topics'
        assert classify(target,'其他企业扩产','扩产新闻<footer>示例光电</footer>')[1]=='customer_mismatch'
        old=(datetime.now(ZONE)-timedelta(days=40)).date().isoformat()
        result, _=ingest(db,c['id'],published=old)
        assert result['quality_status']=='archived'
    assert client.get('/api/v1/customer-signals').json()['total']==0


def test_customer_queries_keep_target_and_payload_and_queue(client, database):
    c=customer(client)
    with database.begin() as db:
        rule=db.get(Rule,c['rule_id'])
        lane=choose(db,rule,['duckduckgo'],now=1000)
        assert '示例光电' in lane.query
        search=service.start_rule(db,rule,'customer-search')
        search_id=search.id
    public, customers=[],[]
    service.dispatch_pending(public.append,customers.append)
    assert customers==[search_id] and public==[]
    token,*_=service.claim(search_id)
    service.finish(search_id,token,results=[{'url':'https://example.com/result','title':'x','raw_content':'x','content_kind':'search_excerpt'}])
    with database() as db:
        child=db.scalar(select(Task).where(Task.parent_id==search_id))
        assert child.payload['source_type']=='customer_watch' and child.payload['customer_id']==c['id']
    assert client.post('/api/v1/customers',json={'name':c['name']}).status_code==409


def test_customer_aging_and_public_purge_preserve_evidence(client, database):
    from scout.purge_bulletins import purge
    c=customer(client)
    with database.begin() as db:
        result,task=ingest(db,c['id'])
        task.status='succeeded'
        task.result=result
        s=db.get(CustomerSignal,result['signal_id'])
        s.created_at-=31*86400
    archive_expired(database)
    assert client.get('/api/v1/customer-signals').json()['total']==0
    purge(database)
    with database() as db:
        s=db.get(CustomerSignal,result['signal_id'])
        assert s.quality_status=='archived' and db.get(Document,s.document_id)
        assert db.get(Task,task.id).payload.get('raw_content')


def test_official_identity_requires_exact_host_and_unknown_date_can_be_verified(client, database):
    c=customer(client)
    with database.begin() as db:
        target=db.get(Customer,c['id'])
        target.website='https://www.example.com/'
        assert classify(target,'新建生产基地','公司新建生产基地扩大产能',url='https://example.com/news')[0]
        assert classify(target,'新建生产基地','公司新建生产基地扩大产能',url='https://example.com.evil.test/news')[1]=='customer_mismatch'
        result, task=ingest(db,c['id'],published='unknown')
        assert result['quality_status']=='archived'
        task.payload={**task.payload,'published_at':datetime.now(ZONE).date().isoformat()}
        verified=service.save_item(db,task)
        assert verified['signal_id']==result['signal_id'] and verified['quality_status']=='active'
        assert db.scalar(select(func.count()).select_from(CustomerSignal))==1
        assert db.scalar(select(func.count()).select_from(Document))==2


def test_monitor_demand_stays_promoted_after_duplicate_collection(client, database):
    from scout.ai_review import tick
    from scout.config import Settings
    c=customer(client)
    with database.begin() as db:
        result,_=ingest(db,c['id'])
    tick(Settings(_env_file=None,deepseek_api_key='test-key'),database,
         reviewer=lambda *args:{'decision':'buyer_demand','reason':'明确采购需求','evidence':'建设MES数字化系统'})
    with database.begin() as db:
        duplicate,_=ingest(db,c['id'],url='https://example.com/mirror')
        assert duplicate['duplicate']
        item=db.get(Item,result['signal_id'])
        assert item.information_kind=='opportunity' and item.quality_status=='active'
        assert 'https://example.com/mirror' in item.source_urls
    snap=client.get('/api/v1/display/snapshot').json()
    assert snap['pending_count']==1 and snap['customer_items']==[]


def test_edit_customer_urls_preserves_state_and_inflight_identity(client, database):
    from sqlalchemy import select

    from scout import service
    from scout.models import Rule, Task
    c = client.post('/api/v1/customers',json={'name':'示例制造有限公司','aliases':['示例制造'],
        'reference_urls':'https://example.com，https://news.example.org/account\nhttps://example.com'}).json()
    assert len(c['reference_urls']) == 2
    with database() as db:
        rule = db.get(Rule,c['rule_id'])
        assert 'site:news.example.org' in rule.query
    service.schedule_due()
    result=client.patch('/api/v1/customers/'+c['id'],json={'name':'示例制造科技有限公司','aliases':['示例科技'],
        'reference_urls':'https://media.example.net/u/123'}).json()
    assert result['enabled'] is True
    with database() as db:
        task=db.scalar(select(Task).where(Task.rule_id==c['rule_id']))
        assert task.payload['customer_snapshot']['name']=='示例制造有限公司'
        assert db.get(Rule,c['rule_id']).version==2
    client.patch('/api/v1/rules/'+c['rule_id'],json={'enabled':False})
    assert client.patch('/api/v1/customers/'+c['id'],json={'name':'示例制造科技有限公司','reference_urls':[]}).json()['enabled'] is False
    assert client.patch('/api/v1/customers/'+c['id'],json={'name':'示例制造科技有限公司','reference_urls':'javascript:alert(1)'}).status_code==422


def test_media_reference_domain_does_not_imply_customer_identity():
    from types import SimpleNamespace

    from scout.customers import classify
    customer=SimpleNamespace(name='示例科技',aliases=[],website=None,reference_urls=['https://news.example.org/account'])
    result,reason=classify(customer,'另一企业扩产','另一企业新建生产基地。','2026-11-15','https://news.example.org/unrelated')
    assert result is None and reason=='customer_mismatch'


def test_batch_assign_owner_updates_customer_and_rule(client, database):
    c = customer(client)
    r = client.post('/api/v1/users', json={'username':'对接人张三','password':'passw0rd123',
                                           'display_name':'张三','role':'member'})
    assert r.status_code == 201, r.text
    owner_id = r.json()['id']

    r = client.post('/api/v1/customers/batch-owner',
                    json={'customer_ids': [c['id']], 'owner_user_id': owner_id})
    assert r.status_code == 200 and r.json()['updated'] == 1
    rows = client.get('/api/v1/customers').json()
    row = next(x for x in rows if x['id'] == c['id'])
    assert row['owner_user_id'] == owner_id and row['owner_name'] == '张三'

    with database() as db:
        assert db.get(Rule, c['rule_id']).owner_user_id == owner_id

    # 清除对接人
    r = client.post('/api/v1/customers/batch-owner',
                    json={'customer_ids': [c['id']], 'owner_user_id': None})
    assert r.status_code == 200
    rows = client.get('/api/v1/customers').json()
    row = next(x for x in rows if x['id'] == c['id'])
    assert row['owner_user_id'] is None and row['owner_name'] is None

    # 不存在的用户 → 422；不存在的客户 → 404
    assert client.post('/api/v1/customers/batch-owner',
                       json={'customer_ids': [c['id']], 'owner_user_id': 'nope'}).status_code == 422
    assert client.post('/api/v1/customers/batch-owner',
                       json={'customer_ids': ['missing'], 'owner_user_id': owner_id}).status_code == 404


def test_create_customer_with_owner_user_id(client, database):
    r = client.post('/api/v1/users', json={'username':'导入对接人','password':'passw0rd123',
                                           'display_name':'李四','role':'member'})
    assert r.status_code == 201, r.text
    owner_id = r.json()['id']

    # 管理员创建时直接指定对接人
    r = client.post('/api/v1/customers',
                    json={'name':'导入客户股份有限公司','owner_user_id':owner_id})
    assert r.status_code == 201, r.text
    with database() as db:
        assert db.get(Rule, r.json()['rule_id']).owner_user_id == owner_id

    # 不存在的用户 → 422
    assert client.post('/api/v1/customers',
                       json={'name':'另一家客户股份有限公司','owner_user_id':'nope'}).status_code == 422

    # PATCH 忽略 owner_user_id，不报错也不改对接人
    rows = client.get('/api/v1/customers').json()
    row = next(x for x in rows if x['name'] == '导入客户股份有限公司')
    assert client.patch('/api/v1/customers/'+row['id'],
                        json={'name':'导入客户股份有限公司','owner_user_id':'whatever'}).status_code == 200
    with database() as db:
        assert db.get(Rule, row['rule_id']).owner_user_id == owner_id
