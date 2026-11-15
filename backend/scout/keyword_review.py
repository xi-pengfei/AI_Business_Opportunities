"""Advisory keyword review: returns a draft; never saves or starts collection."""
import json

import httpx

from scout.prompts import load_prompt


def review(name, query, config, client=None):
    if not config.deepseek_api_key:
        raise ValueError('ai_key_missing')
    body={'model':config.deepseek_model,'thinking':{'type':'disabled'},'max_tokens':1600,
          'response_format':{'type':'json_object'},'messages':[
              {'role':'system','content':load_prompt('legacy-keyword-review')},
              {'role':'user','content':json.dumps({'name':name,'keywords':query.splitlines()},ensure_ascii=False)}]}
    def request(c):
        response=c.post('https://api.deepseek.com/chat/completions',json=body,
                        headers={'Authorization':'Bearer '+config.deepseek_api_key})
        response.raise_for_status()
        r=json.loads(response.json()['choices'][0]['message']['content'])
        if not isinstance(r,dict) or not isinstance(r.get('name'),str) or not 1<=len(r['name'].strip())<=120:
            raise ValueError('invalid_review')
        words,notes=r.get('keywords'),r.get('notes')
        if (not isinstance(words,list) or not 1<=len(words)<=30 or
                any(not isinstance(w,str) or not w.strip() or '\n' in w for w in words) or
                not isinstance(notes,list) or len(notes)>6 or any(not isinstance(n,str) or len(n)>500 for n in notes)):
            raise ValueError('invalid_review')
        query='\n'.join(dict.fromkeys(w.strip() for w in words))
        if len(query)>500:
            raise ValueError('invalid_review')
        return {'name':r['name'].strip(),'query':query,'notes':notes,'model':config.deepseek_model}
    if client is not None:
        return request(client)
    with httpx.Client(timeout=45) as c:
        return request(c)
