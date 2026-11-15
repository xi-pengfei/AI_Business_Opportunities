import json

import httpx
import pytest
from test_dingtalk import seed

from scout.config import Settings
from scout.geography import locate, tick
from scout.models import Item


def test_geography_rejects_nonliteral_and_agency_evidence():
    raw = '采购人：武汉市中心医院；代理机构：北京代理公司。'
    for basis, evidence in [('agency', '代理机构：北京代理公司'), ('buyer', '采购人位于北京市')]:
        answer = dict(region='北京', basis=basis, evidence=evidence, place='北京')
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            'choices': [{'message': {'content': json.dumps(answer)}}]}))) as client:
            with pytest.raises(ValueError, match='unsupported_region'):
                locate('采购', raw, Settings(_env_file=None, deepseek_api_key='test'), client)


def test_enrichment_preserves_business_state_and_unknown_is_not_guessed(database):
    seed(database)
    config = Settings(_env_file=None, deepseek_api_key='test')
    assert tick(config, database, resolver=lambda *a: {'region': '湖北', 'evidence': '采购人：武汉市中心医院'}, now=1000) == 'located'
    assert tick(config, database, resolver=lambda *a: {'region': None, 'reason': '无所在地'}, now=1001) == 'unknown'
    assert tick(config, database, now=1002) == 'empty'
    with database() as db:
        assert db.get(Item, 'item-0').region == '湖北'
        assert db.get(Item, 'item-1').region is None
        assert db.get(Item, 'item-0').ai_review['decision'] == 'buyer_demand'
        assert db.get(Item, 'item-0').quality_status == 'active'


def test_map_counts_only_opportunities_not_monitor_news(database, client):
    seed(database)
    with database.begin() as db:
        db.get(Item, 'item-0').region = '湖北'
        news = db.get(Item, 'item-1')
        news.information_kind = 'customer_update'
        news.source_type = 'customer_watch'
        news.region = '北京'
    data = client.get('/api/v1/display/snapshot').json()
    assert data['regions'] == [{'name': '湖北', 'count': 1}]
    assert data['region_unknown'] == 0
    assert client.get('/api/v1/display/items?start=0&end=1000&region=北京').json()['total'] == 0
    with database.begin() as db:
        db.get(Item, 'item-0').region = None
    data = client.get('/api/v1/display/snapshot').json()
    assert data['regions'] == []
    assert data['region_unknown'] == 1
