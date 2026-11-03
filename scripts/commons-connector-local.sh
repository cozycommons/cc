#!/usr/bin/env bash
# Configure and serve only the isolated loopback MCP OAuth exercise.
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
case "${1:-}" in setup|serve|test) ;; *) echo 'Usage: scripts/commons-connector-local.sh setup|serve|test [--interactive]' >&2; exit 2 ;; esac
if [[ $# -gt 2 || ( $# -eq 2 && ( "$1" != test || "$2" != --interactive ) ) ]]; then
  echo 'Only test accepts --interactive.' >&2
  exit 2
fi
eval "$(scripts/dice-supabase.sh status -o env)"
if [[ "${API_URL:-}" != 'http://127.0.0.1:54321' ||
      "${DB_URL:-}" != 'postgresql://postgres:postgres@127.0.0.1:54322/postgres' ]]; then
  echo 'Refusing non-loopback Supabase configuration.' >&2
  exit 1
fi
local_key="${SERVICE_ROLE_KEY:-${SECRET_KEY:-}}"
: "${local_key:?Local Supabase service key missing}"
local_config="$repo_dir/.dice-dev/commons-mcp.json"
if [[ "$1" == setup ]]; then
  mkdir -p "$repo_dir/.dice-dev"
  env -i PATH="$PATH" HOME="$HOME" LOCAL_KEY="$local_key" LOCAL_CONFIG="$local_config" \
    backend/.venv/bin/python - <<'PY'
import base64
import json
import os
import secrets
from pathlib import Path
import httpx
from cryptography.fernet import Fernet

path = Path(os.environ['LOCAL_CONFIG'])
if path.exists():
    raise SystemExit('Local MCP configuration already exists; reuse it or remove it after a stack reset.')
response = httpx.post('http://127.0.0.1:54321/auth/v1/admin/oauth/clients',
    headers={'apikey': os.environ['LOCAL_KEY'], 'Authorization': 'Bearer ' + os.environ['LOCAL_KEY']},
    json={'client_name': 'Cozy Commons loopback MCP',
          'redirect_uris': ['http://127.0.0.1:8000/auth/callback'],
          'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})
if response.status_code >= 400:
    raise SystemExit(f'Local OAuth client registration failed: HTTP {response.status_code}')
client = response.json()
config = {'CC_MCP_BASE_URL': 'http://127.0.0.1:8000',
          'CC_MCP_OAUTH_CLIENT_ID': client['client_id'],
          'CC_MCP_OAUTH_CLIENT_SECRET': client['client_secret'],
          'CC_MCP_JWT_SIGNING_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
          'CC_MCP_STORAGE_ENCRYPTION_KEY': Fernet.generate_key().decode()}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    json.dump(config, output)
print('Local confidential OAuth client registered; private keys saved under ignored .dice-dev/.')
PY
else
  exec env -i PATH="$PATH" HOME="$HOME" LANG="${LANG:-C.UTF-8}" \
    LOCAL_KEY="$local_key" LOCAL_CONFIG="$local_config" LOCAL_MODE="$1" LOCAL_INTERACTIVE="${2:-}" \
    backend/.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import runpy
import sys

config = json.loads(Path(os.environ['LOCAL_CONFIG']).read_text())
assert config['CC_MCP_BASE_URL'] == 'http://127.0.0.1:8000'
os.environ.update(config)
os.environ.update(SUPABASE_URL='http://127.0.0.1:54321',
    SUPABASE_SERVICE_KEY=os.environ['LOCAL_KEY'],
    LOCAL_SUPABASE_SERVICE_ROLE_KEY=os.environ['LOCAL_KEY'],
    DICE_LOCAL_HARNESS='true', ENABLE_SCHEDULER='false')
if os.environ['LOCAL_MODE'] == 'test':
    sys.argv = ['scripts/commons-connector-e2e.py']
    if os.environ.get('LOCAL_INTERACTIVE'):
        sys.argv.append('--interactive')
    runpy.run_path(sys.argv[0], run_name='__main__')
else:
    os.chdir('backend')
    sys.path.insert(0, str(Path.cwd()))
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=8000, access_log=False)
PY
fi
