from sqlalchemy import select

from scout.models import Rule, SearchCursor, Task
from scout.providers import ProviderError
from scout.search_plan import choose, complete, variants


def test_each_query_owns_pages_and_empty_search_returns_to_front(database):
    with database.begin() as db:
        rule=Rule(name='test',query='甲\n乙',provider='searxng',interval_seconds=0)
        db.add(rule)
        db.flush()
        first=choose(db,rule,['duckduckgo'],1000)
        task=Task(payload={'search_cursor_id':first.id})
        complete(db,task,[],None,1000)
        assert first.page==2
        second=choose(db,rule,['duckduckgo'],1001)
        assert second.id != first.id and second.page==1
        complete(db,Task(payload={'search_cursor_id':second.id}),[],None,1001)
        again=choose(db,rule,['duckduckgo'],1004)
        assert again.id==first.id and again.page==2
        complete(db,task,[],None,1004)
        assert first.page==1 and first.next_at==1304
        complete(db,Task(payload={'search_cursor_id':second.id}),[],None,1005)
        assert choose(db,rule,['duckduckgo'],1100) is None
        assert choose(db,rule,['duckduckgo'],1304).page==1
        complete(db,task,[{'url':'https://example.com/new'}],None,1304)
        assert first.last_result_at==1304


def test_rate_limit_cools_entire_engine_and_preserves_other_source(database):
    with database.begin() as db:
        rule=Rule(name='test',query='甲\n乙',provider='searxng',interval_seconds=0)
        db.add(rule)
        db.flush()
        lane=choose(db,rule,['duckduckgo','brave'],1000)
        complete(db,Task(payload={'search_cursor_id':lane.id}),[],ProviderError('searxng_rate_limited'),1000)
        others=db.scalars(select(SearchCursor).where(SearchCursor.engine==lane.engine)).all()
        assert all(c.next_at>=1300 for c in others)
        next_lane=choose(db,rule,['duckduckgo','brave'],1001)
        assert next_lane.engine!=lane.engine
        assert lane.empty_streak==0


def test_repeated_nonempty_page_stops_deeper_paging(database):
    with database.begin() as db:
        rule=Rule(name='test',query='甲',provider='searxng',interval_seconds=0)
        db.add(rule)
        db.flush()
        lane=choose(db,rule,['duckduckgo'],1000)
        task=Task(payload={'search_cursor_id':lane.id})
        complete(db,task,[{'url':'https://example.com/a'}],None,1000)
        complete(db,task,[{'url':'https://example.com/a'}],None,1004)
        assert lane.outcome=='repeated_page' and lane.page==1 and lane.next_at==1304
    assert 'ERP 采购公告' in variants('ERP 系统 升级改造 采购公告')


def test_first_page_is_revisited_even_when_deeper_pages_still_have_results(database):
    with database.begin() as db:
        rule=Rule(name='test',query='甲',provider='searxng',interval_seconds=0)
        db.add(rule)
        db.flush()
        lane=choose(db,rule,['duckduckgo'],1000)
        lane.page=8
        lane.next_at=1005
        db.flush()
        assert choose(db,rule,['duckduckgo'],1301).page == 1
