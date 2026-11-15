from scout.collector_history import collector_history
from scout.display import collector_status
from scout.models import Event, Rule, Task


def test_history_keeps_retry_failure_and_success_without_counting_ingest_or_demo(database):
    with database.begin() as db:
        db.add(Rule(id='r', name='private name', query='private query', enabled=True, provider='searxng'))
        db.flush()
        for ident, kind, demo, result in [('search','search',False,{'discovered':8}), ('zero','search',False,{'discovered':0}), ('demo','search',True,{'discovered':99}), ('ingest','ingest',False,{'discovered':99})]:
            db.add(Task(id=ident, rule_id='r', kind=kind, payload={}, result=result, status='succeeded', is_demo=demo, updated_at=1100, idempotency_key=ident))
        db.flush()
        for task, kind, stamp, code, demo in [('search','task.retry_wait',950,'search_request_failed',False),('search','task.succeeded',1000,None,False),('search','task.succeeded',1001,None,False),('zero','task.succeeded',1100,None,False),('demo','task.succeeded',1100,None,True),('ingest','task.succeeded',1100,None,False),('search','task.retry_wait',1150,'search_rate_limited',False)]:
            db.add(Event(task_id=task, kind=kind, created_at=stamp, data={'error_code':code}, is_demo=demo))
    with database() as db:
        buckets = collector_history(db, ['r'], False, 1200)['r']
        assert sum(b['results'] or 0 for b in buckets) == 8
        assert sum(b['successes'] for b in buckets) == 2
        assert sum(b['failures'] for b in buckets) == 1
        assert sum(b['warnings'] for b in buckets) == 1
        assert any(b['results'] == 0 and b['successes'] == 1 for b in buckets)
        assert buckets[-1]['results'] is None and buckets[-1]['successes'] == 0
        row = collector_status(db, False, 'display')[0]
        assert row['name'] == '采集规则' and row['query'] == ''
        assert row['last_success_at'] == 1100
        assert 'private' not in str(row)


def test_running_unknown_and_window_boundaries(database):
    with database.begin() as db:
        db.add(Rule(id='r',name='empty',query='',provider='searxng',enabled=True))
        db.flush()
        db.add(Task(id='t',rule_id='r',kind='search',payload={},result={},idempotency_key='t'))
        db.flush()
        for stamp, kind in [(150,'task.running'),(200,'task.succeeded'),(3601,'task.failed')]:
            db.add(Event(task_id='t',kind=kind,created_at=stamp,data={}))
    with database() as db:
        buckets=collector_history(db,['r'],False,3600)['r']
        assert buckets[0]['start'] == 150
        assert buckets[0]['running'] == 1 and buckets[0]['successes'] == 1
        assert buckets[0]['results'] is None
        assert sum(b['failures'] for b in buckets) == 0
