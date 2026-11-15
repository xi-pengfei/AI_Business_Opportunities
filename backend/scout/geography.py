"""Independent evidence-backed geography enrichment; never gates delivery."""
import json
import time

import httpx
from sqlalchemy import select

from scout.db import Session
from scout.models import Document, Item
from scout.prompts import load_prompt
from scout.quality import PROVINCES


def locate(title, raw, config, client=None):
    if len(raw) > 24000:
        return {'region': None, 'reason': '原文过长，待定位'}
    body = {'model': config.deepseek_model, 'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'}, 'max_tokens': 500,
            'messages': [{'role': 'system', 'content': load_prompt('geography')},
                         {'role': 'user', 'content': json.dumps({'title': title, 'body': raw}, ensure_ascii=False)}]}
    def request(c, repair=True):
        response = c.post('https://api.deepseek.com/chat/completions', json=body,
                          headers={'Authorization': 'Bearer ' + config.deepseek_api_key})
        response.raise_for_status()
        result = json.loads(response.json()['choices'][0]['message']['content'])
        if not isinstance(result, dict):
            raise ValueError('invalid_region')
        region = result.get('region')
        if region is None:
            return {'region': None, 'reason': str(result.get('reason', '依据不足'))[:300]}
        # Normalize administrative suffixes, never infer a location from a company alias.
        aliases = {p + suffix: p for p in PROVINCES for suffix in ('省', '市', '自治区', '特别行政区')}
        aliases.update({'广西壮族自治区': '广西', '宁夏回族自治区': '宁夏', '新疆维吾尔自治区': '新疆'})
        region = aliases.get(region, region)
        result['region'] = region
        quote, place = result.get('evidence'), result.get('place')
        if isinstance(place, str) and isinstance(quote, str) and place not in quote and place.endswith('市') and place[:-1] in quote:
            place = place[:-1]
            result['place'] = place
        if (region not in PROVINCES or result.get('basis') not in ('project', 'buyer')
                or not isinstance(quote, str) or not 4 <= len(quote) <= 100
                or not isinstance(place, str) or len(place) < 2 or place not in quote
                or quote not in title + '\n' + raw):
            if repair:
                body['messages'].extend([
                    {'role': 'assistant', 'content': json.dumps(result, ensure_ascii=False)},
                    {'role': 'user', 'content': load_prompt("geography-repair")},
                ])
                return request(c, repair=False)
            raise ValueError('unsupported_region')
        return {k: result.get(k) for k in ('region', 'basis', 'place', 'evidence', 'reason')}
    if client is not None:
        return request(client)
    with httpx.Client(timeout=35) as c:
        return request(c)


def tick(config, sessions=Session, resolver=locate, now=None):
    if not config.deepseek_api_key:
        return 'not_configured'
    now = now or time.time()
    with sessions.begin() as db:
        item = db.scalar(select(Item).where(
            Item.is_demo.is_(False), Item.quality_status == 'active',
            Item.information_kind.in_(('opportunity', 'demand')),
            Item.ai_review['decision'].as_string() == 'buyer_demand',
            Item.ai_review['geography']['checked_at'].as_float().is_(None),
            (Item.ai_review['geography']['retry_at'].as_float().is_(None)) |
            (Item.ai_review['geography']['retry_at'].as_float() <= now),
        ).order_by(Item.created_at).with_for_update(skip_locked=True).limit(1))
        if item is None:
            return 'empty'
        old = item.ai_review.get('geography', {})
        attempts = old.get('attempts', 0) + 1
        try:
            result = resolver(item.title, db.get(Document, item.document_id).raw_content, config)
        except Exception as exc:
            result = {'error': type(exc).__name__, 'attempts': attempts, 'retry_at': now + 120}
            if attempts >= 3:
                result['checked_at'] = now
            item.ai_review = {**item.ai_review, 'geography': result}
            return 'failed'
        item.region = result.get('region')
        item.region_evidence = result.get('evidence') if item.region else None
        item.ai_review = {**item.ai_review, 'geography': {**result, 'checked_at': now, 'attempts': attempts}}
        return 'located' if item.region else 'unknown'
