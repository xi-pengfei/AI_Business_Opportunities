import json

import httpx
import pytest

from scout.config import Settings
from scout.product_rules import ProductSpec, review_product
from scout.prompts import NAMES, load_prompt


def test_default_prompt_files_are_present_and_nonempty(monkeypatch):
    monkeypatch.delenv('AI_SETTINGS_DIR', raising=False)
    assert len(NAMES)==7
    for name in NAMES:
        assert len(load_prompt(name))>30


def test_changes_are_read_on_next_model_call(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_SETTINGS_DIR',str(tmp_path))
    prompt=tmp_path/'product-rule-review.md'
    sent=[]
    def respond(req):
        sent.append(json.loads(req.content)['messages'][0]['content'])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'product':'MES','synonyms':[],'actions':['采购公告'],'notes':[]})}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as c:
        prompt.write_text('第一次自定义规则',encoding='utf-8')
        review_product(ProductSpec(product='MES'),Settings(_env_file=None,deepseek_api_key='test'),c)
        prompt.write_text('第二次自定义规则',encoding='utf-8')
        review_product(ProductSpec(product='MES'),Settings(_env_file=None,deepseek_api_key='test'),c)
    assert sent==['第一次自定义规则','第二次自定义规则']


def test_invalid_prompt_blocks_call_instead_of_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_SETTINGS_DIR',str(tmp_path))
    with pytest.raises(ValueError,match='unavailable'):
        load_prompt('opportunity-review')
    prompt=tmp_path/'opportunity-review.md'
    for data,reason in [(b' \n','empty'),(b'\xff','unavailable'),(b'x'*65537,'too_large')]:
        prompt.write_bytes(data)
        with pytest.raises(ValueError,match=reason):
            load_prompt('opportunity-review')
    with pytest.raises(ValueError,match='unknown'):
        load_prompt('../../.env')
    prompt.write_text('已修复',encoding='utf-8-sig')
    assert load_prompt('opportunity-review')=='已修复'
