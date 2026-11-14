"""Run a backend command against the project's isolated local containers."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = os.environ.copy()
for line in (root / '.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        env.setdefault(key, value)
env.setdefault('DATABASE_URL', f"postgresql+psycopg://scout:{env['POSTGRES_PASSWORD']}@127.0.0.1:55436/scout")
env.setdefault('REDIS_URL', 'redis://127.0.0.1:56386/0')
env['PATH'] = str(root / 'backend/.venv/bin') + os.pathsep + env['PATH']
os.chdir(root / 'backend')
if len(sys.argv) < 2:
    raise SystemExit('Usage: python3 scripts/local_backend.py <command> [args...]')
os.execvpe(sys.argv[1], sys.argv[1:], env)
