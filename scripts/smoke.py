"""Exercise the running local API/worker. Creates labeled demo rules only."""
import json
import time
import urllib.request
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines() if '=' in line)
base = 'http://127.0.0.1:58100/api/v1'

def api(path, body=None, key=None):
    headers = {'Authorization': 'Bearer ' + config['ADMIN_TOKEN']}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if key:
        headers['Idempotency-Key'] = key
    req = urllib.request.Request(base+path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

live_before = api('/display/snapshot')['item_count']
rule = api('/rules', {'name':'开发验收 · 供应商对账', 'query':'供应商 对账 审批', 'provider':'demo'})
key = str(uuid.uuid4())
task = api(f"/rules/{rule['id']}/run", {}, key)
assert task['id'] == api(f"/rules/{rule['id']}/run", {}, key)['id']
for _ in range(25):
    snapshot = api('/display/snapshot?demo=true')
    children = [t for t in api('/tasks?demo=true') if t['parent_id'] == task['id']]
    if children and all(t['status'] == 'succeeded' for t in children) and api('/tasks/'+task['id'])['status'] == 'succeeded':
        break
    time.sleep(1)
else:
    raise SystemExit('Pipeline did not finish within 25 seconds')
assert api('/display/snapshot')['item_count'] == live_before, 'demo changed live mode counts'
assert len(api('/items?demo=true')) >= 1
Path(root/'runtime/checks/smoke.json').write_text(json.dumps({'rule_id':rule['id'],'task_id':task['id'],'item_count':snapshot['item_count'],'result':'passed'}, indent=2))
print('PASS: API → PostgreSQL outbox → Redis → Celery → evidence → item → snapshot; idempotency and demo isolation.')
