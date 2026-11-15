"""One product per rule; aliases are alternatives, never additional constraints."""
import json
import re

import httpx
from pydantic import BaseModel, Field, field_validator

from scout.prompts import load_prompt

DEFAULT_ACTIONS = ['采购公告', '招标公告', '采购意向']


class ProductSpec(BaseModel):
    product: str = Field(min_length=1, max_length=80)
    synonyms: list[str] = Field(default_factory=list, max_length=20)
    actions: list[str] = Field(default_factory=lambda: DEFAULT_ACTIONS.copy(), min_length=1, max_length=20)

    regions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('regions', mode='before')
    @classmethod
    def clean_regions(cls, value):
        if isinstance(value,str):
            value=re.split(r'[\s,，;；]+',value)
        if not isinstance(value,list) or any(not isinstance(v,str) for v in value):
            raise ValueError('地区请用空格、逗号或换行分隔')
        words=list(dict.fromkeys(part for v in value for part in re.split(r'[\s,，;；]+',v.strip()) if part))
        if any(len(w)>40 for w in words):
            raise ValueError('单个地区名称最多40字')
        return words

    @field_validator('product')
    @classmethod
    def clean_product(cls, value):
        value=value.strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError('请填写一个产品或业务名称')
        return value

    @field_validator('synonyms', 'actions', mode='before')
    @classmethod
    def clean_terms(cls, value):
        if isinstance(value, str):
            value=re.split(r'[,，;；\n\r]+', value)
        if not isinstance(value, list) or any(not isinstance(v,str) for v in value):
            raise ValueError('请按行填写名称')
        words=list(dict.fromkeys(v.strip() for v in value if v.strip()))
        if any(len(w)>80 or '\n' in w or '\r' in w for w in words):
            raise ValueError('每个名称最多80字，不能跨行')
        return words

    def searches(self):
        names=list(dict.fromkeys([self.product, *self.synonyms]))
        return list(dict.fromkeys(' '.join(filter(None,(name,action,region)))
                                  for name in names for action in self.actions for region in (self.regions or [''])))


class ProductInput(ProductSpec):
    enabled: bool = False


def review_product(spec, config, client=None):
    if not config.deepseek_api_key:
        raise ValueError('ai_key_missing')
    prompt=load_prompt("product-rule-review")
    body={'model':config.deepseek_model,'thinking':{'type':'disabled'},'max_tokens':1800,
          'response_format':{'type':'json_object'},'messages':[{'role':'system','content':prompt},
          {'role':'user','content':json.dumps(spec.model_dump(),ensure_ascii=False)}]}
    def run(c):
        r=c.post('https://api.deepseek.com/chat/completions',json=body,headers={'Authorization':'Bearer '+config.deepseek_api_key})
        r.raise_for_status()
        result=json.loads(r.json()['choices'][0]['message']['content'])
        # Geography is user-owned scope; AI cannot silently erase or broaden it.
        if not isinstance(result,dict):
            raise ValueError("invalid_review")
        result["regions"]=spec.regions
        checked=ProductSpec.model_validate(result)
        notes=result.get('notes',[])
        if not isinstance(notes,list) or len(notes)>6 or any(not isinstance(n,str) or len(n)>500 for n in notes):
            raise ValueError('invalid_review')
        return {**checked.model_dump(),'queries':checked.searches(),'notes':notes,'model':config.deepseek_model}
    if client is not None:
        return run(client)
    with httpx.Client(timeout=45) as c:
        return run(c)
