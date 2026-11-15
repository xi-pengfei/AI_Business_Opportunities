import json

import httpx
import pytest
from sqlalchemy import func, select

from scout.config import Settings
from scout.keyword_review import review
from scout.models import Rule, Task
from scout.search_plan import variants


def test_independent_keywords_are_not_lost_or_cross_combined():
    searches=variants('财务共享\nHR 人力资源系统\nWMS 仓储管理系统\nRAG 知识库')
    for keyword in ('财务共享','HR 人力资源系统','WMS 仓储管理系统','RAG 知识库'):
        assert keyword+' 采购公告' in searches
    assert not any('HR' in s and 'WMS' in s for s in searches)


def test_review_only_returns_draft_and_does_not_run(client,database,monkeypatch):
    monkeypatch.setattr('scout.keyword_review.review',lambda *a:{'name':'企业管理','query':'HR 人力资源系统\nWMS 仓储管理系统','notes':['分开搜索'],'model':'test'})
    r=client.post('/api/v1/rules/review',json={'name':'管理','query':'HR WMS'})
    assert r.status_code==200 and '分开搜索' in r.json()['notes']
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Rule))==0
        assert db.scalar(select(func.count()).select_from(Task))==0
    assert client.post('/api/v1/rules/review',json={'name':'管理','query':'HR'},headers={'Authorization':'Bearer test-display'}).status_code==403


def test_review_invalid_output_and_outage_do_not_save(client,database,monkeypatch):
    config=Settings(_env_file=None,deepseek_api_key='test')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'name':'测试','keywords':['x'*501],'notes':[]})}}]}))) as c:
        with pytest.raises(ValueError):
            review('测试','ERP',config,c)
    def fail(*a): raise TimeoutError('private')
    monkeypatch.setattr('scout.keyword_review.review',fail)
    r=client.post('/api/v1/rules/review',json={'name':'测试','query':'ERP'})
    assert r.status_code==503 and 'private' not in r.text
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Rule))==0
