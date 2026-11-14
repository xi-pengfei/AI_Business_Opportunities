#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
if p.exists():
    print('.env already exists; left unchanged.')
else:
    p.touch(mode=0o600)
    p.write_text('POSTGRES_PASSWORD='+secrets.token_hex(24)+'\nADMIN_TOKEN='+secrets.token_urlsafe(32)+'\nDISPLAY_TOKEN='+secrets.token_urlsafe(32)+'\nTAVILY_API_KEY=\nALLOW_DEMO=false\n')
    print('Created .env with private local credentials. No credentials printed.')
PY
