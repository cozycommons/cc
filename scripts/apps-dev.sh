#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
unset APPS_POSTGRES_PASSWORD
if [ -n "${DOCKER_CONTEXT:-}" ]; then
  DOCKER_ENDPOINT="$(docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')"
else
  DOCKER_ENDPOINT="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"
fi
case "$DOCKER_ENDPOINT" in
  unix://*) ;;
  *) echo 'The apps prototype requires a local Unix-socket Docker endpoint.' >&2; exit 1 ;;
esac
case "${1:-help}" in
  setup)
    mkdir -p .apps-dev
    python3 - <<'PY'
import json, pathlib, secrets
p=pathlib.Path('.apps-dev')
for name, content in [('users.json',json.dumps({user:secrets.token_urlsafe(32) for user in ['owner','friend','viewer','outsider']},indent=2)),('compose.env','APPS_POSTGRES_PASSWORD='+secrets.token_hex(32)+'\n')]:
    dest=p/name
    if not dest.exists():
        dest.write_text(content+'\n')
        dest.chmod(0o600)
PY
    python3 -m venv .apps-dev/venv
    .apps-dev/venv/bin/pip install -r backend/app_runtime/requirements.txt
    docker compose --env-file .apps-dev/compose.env -f infra/apps/compose.yaml --profile build build
    ;;
  start)
    docker compose --env-file .apps-dev/compose.env -f infra/apps/compose.yaml up -d manager proxy postgres
    attempts=0
    until curl --noproxy '*' --fail --silent http://127.0.0.1:8091/health >/dev/null 2>&1; do
      attempts=$((attempts + 1))
      if [ "$attempts" -ge 30 ]; then
        echo 'Apps manager did not become ready within 30 seconds.' >&2
        exit 1
      fi
      sleep 1
    done
    ;;
  stop)
    # Stop only containers labelled as this prototype's apps.
    docker ps -q --filter label=cc.apps | while IFS= read -r container; do
      if [ -n "$container" ]; then docker stop "$container"; fi
    done
    docker compose --env-file .apps-dev/compose.env -f infra/apps/compose.yaml stop
    ;;
  status)
    docker compose --env-file .apps-dev/compose.env -f infra/apps/compose.yaml ps
    ;;
  cli|mcp|smoke)
    action="$1"
    shift
    export PYTHONPATH="$ROOT/backend"
    export COMMONS_TOKEN
    COMMONS_TOKEN="$(.apps-dev/venv/bin/python -c 'import json,os; print(json.load(open(".apps-dev/users.json"))[os.environ.get("COMMONS_USER","owner")])')"
    case "$action" in
      cli) exec .apps-dev/venv/bin/python -m app_runtime.cli "$@" ;;
      mcp) exec .apps-dev/venv/bin/python -m app_runtime.mcp_server ;;
      smoke) exec .apps-dev/venv/bin/python -m app_runtime.tests.smoke ;;
    esac
    ;;
  *) echo 'Usage: scripts/apps-dev.sh setup|start|stop|status|cli|mcp|smoke' ;;
esac
