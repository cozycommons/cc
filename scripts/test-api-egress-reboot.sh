#!/usr/bin/env bash
# Restart only a disposable nested Docker daemon. Never restart the host daemon/VM.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
case $(docker context inspect --format '{{.Endpoints.docker.Host}}') in
  unix://*) ;;
  *) echo 'Use a local Unix-socket Docker context.' >&2; exit 1 ;;
esac
compose() {
  if [ -n "${API_EGRESS_COMPOSE:-}" ]; then "$API_EGRESS_COMPOSE" "$@"
  else docker compose "$@"; fi
}
mkdir -p "$HOME/.cache"
work=$(mktemp -d "$HOME/.cache/cc-egress-reboot.XXXXXX")
project="cc-egress-reboot-$$"
daemon="$project-daemon"
export API_RUNTIME_FILE="$work/runtime.env" API_EGRESS_ROOT="$ROOT"
export EGRESS_MODE=enforce EGRESS_SUPABASE_HOST=synthetic.supabase.co EGRESS_DB_HOST=synthetic.pooler.supabase.com
printf '%s\n' 'EGRESS_SECRET_SENTINEL=synthetic-$literal-only' > "$API_RUNTIME_FILE"
chmod 755 "$work"
chmod 644 "$API_RUNTIME_FILE"
files=(--project-directory "$ROOT" -p "$project" -f "$ROOT/deploy/api-egress/compose.yaml" -f "$ROOT/deploy/api-egress/test.compose.yaml")
cleanup() {
  docker logs "$daemon" > "$work/daemon.log" 2>&1 || true
  docker rm -fv "$daemon" >/dev/null 2>&1 || true
  rm -f "$API_RUNTIME_FILE"
}
trap cleanup EXIT
compose "${files[@]}" build
# Keep application DB state for the reboot; otherwise the tmpfs loses initdb data.
# This file belongs only to this synthetic nested daemon.
cat > "$work/reboot.yaml" <<'YAML'
services:
  database-origin:
    tmpfs: !reset []
YAML
# Outer daemon reads these two mounts. Neither host socket nor real secrets is
# mounted into DinD. Its nested root authority is restricted to synthetic data.
docker run -d --privileged --name "$daemon" -e DOCKER_TLS_CERTDIR= \
  -v "$ROOT:$ROOT:ro" -v "$work:$work:ro" docker:dind \
  dockerd --host=unix:///var/run/docker.sock >/dev/null
ready() {
  for attempt in $(seq 1 60); do
    if docker exec "$daemon" docker info >/dev/null 2>&1; then return; fi
    sleep 1
  done
  echo 'Nested Docker failed to start' >&2; return 1
}
ready
# Avoid installing/building anything in the nested daemon. Reuse actual locally
# built images, including the unchanged production API Dockerfile.
docker image inspect postgres:17-alpine >/dev/null 2>&1 || docker pull postgres:17-alpine
docker save "$project-api" "$project-netguard" "$project-proxy" "$project-database" "$project-ingress" postgres:17-alpine |
  docker exec -i "$daemon" docker load >/dev/null
inner() {
  docker exec -e API_RUNTIME_FILE -e API_EGRESS_ROOT -e EGRESS_MODE -e EGRESS_SUPABASE_HOST -e EGRESS_DB_HOST "$daemon" \
    docker compose "${files[@]}" -f "$work/reboot.yaml" "$@"
}
inner up -d --no-build --wait --wait-timeout 120
api=$(inner ps -a -q api)
netguard=$(inner ps -a -q netguard)
proxy=$(inner ps -a -q proxy)
database=$(inner ps -a -q database)
ingress=$(inner ps -a -q ingress)
origin=$(inner ps -a -q database-origin)
# Reboot only the nested daemon. Do not invoke up/start/restart/recover on any
# inner service afterward: Docker restart policies and the namespace gate own it.
for round in 1 2 3; do
  docker exec "$daemon" docker logs "$api" > "$work/api-before-$round.log" 2>&1
  docker restart "$daemon" >/dev/null
  ready
  restored=false
  for attempt in $(seq 1 120); do
    docker exec "$daemon" docker inspect "$api" "$netguard" "$proxy" "$database" "$ingress" "$origin" > "$work/state-$round.json"
    if python3 - "$work/state-$round.json" <<'PYCODE'
import json,sys
states = json.load(open(sys.argv[1]))
ready = len(states) == 6 and all(c['State']['Running'] and not c['State']['Restarting'] for c in states)
ready = ready and all(c['State'].get('Health', {}).get('Status', 'healthy') == 'healthy' for c in states)
sys.exit(0 if ready else 1)
PYCODE
    then restored=true; break; fi
    sleep 1
  done
  [ "$restored" = true ]
  docker exec "$daemon" docker logs "$api" > "$work/api-$round.log" 2>&1
  docker exec "$daemon" docker logs "$netguard" > "$work/netguard-$round.log" 2>&1
  python3 - "$work" "$round" <<'PYCODE'
import json,sys
from pathlib import Path
root, number = Path(sys.argv[1]), int(sys.argv[2])
def events(role, event):
    result = []
    for line in (root / f'{role}-{number}.log').read_text().splitlines():
        if line.startswith('{'):
            item = json.loads(line)
            if item.get('event') == event:
                result.append(item['time_ns'])
    return result
proofs = events('netguard', 'egress_firewall_ready')
starts = events('api', 'egress_app_start')
assert len(proofs) >= number + 1 and len(starts) >= number + 1
before = events('api-before', 'egress_app_start')
new_starts = starts[len(before):]
assert new_starts and all(start >= proofs[-1] for start in new_starts), 'API application started before namespace proof'
print(f'PASS reboot {number}: app started {(starts[-1] - proofs[-1])/1e6:.1f} ms after namespace proof')
PYCODE
  inner exec -T ingress wget -qO- http://127.0.0.1:8000/ready | grep synthetic-egress-api
  inner exec -T api python -m api_egress_entrypoint python /egress-probe.py
  echo "PASS reboot $round: every service restored automatically, no manual recovery"
done
echo "PASS three isolated daemon reboots; evidence: $work"
