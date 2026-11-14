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


def test_customer_signal_isolated_from_public_rejection_and_push(client, database):
    c = customer(client)
    assert client.get('/api/v1/rules').json() == []
    with database.begin() as db:
        db.add(RemovedEvidence(url_hash=hashlib.sha256(b'https://example.com/news/1').hexdigest(),content_hash='ignored'))
        result, _ = ingest(db,c['id'])
        assert result['quality_status'] == 'active'
        duplicate, _ = ingest(db,c['id'],url='https://example.com/mirror')
        assert duplicate['duplicate']
        assert db.scalar(select(func.count()).select_from(CustomerSignal)) == 1
        assert db.scalar(select(func.count()).select_from(Item)) == 0
        assert db.scalar(select(func.count()).select_from(Delivery)) == 0
    rows=client.get('/api/v1/customer-signals').json()
    assert rows['total']==1 and rows['items'][0]['matched_name']=='示例光电股份有限公司'
    snap=client.get('/api/v1/display/snapshot').json()
    assert snap['item_count']==0 and snap['collectors']==[]
    assert all(r[1]==0 for r in snap['collection_history'])
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
