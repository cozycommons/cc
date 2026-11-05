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
recover() {
  inner down
  inner up -d --no-build --wait --wait-timeout 120
  inner exec -T ingress wget -qO- http://127.0.0.1:8000/ready | grep synthetic-egress-api
  inner exec -T api python -m api_egress_entrypoint python /egress-probe.py
}
recover
# Equivalent to a clean host reboot from the inner Docker daemon's perspective:
# all inner processes/namespaces go away, then restart policies run without Compose.
docker restart "$daemon" >/dev/null
ready
# API deliberately has no daemon restart policy: it cannot run in the brief
# interval before netguard restores the firewall. Sidecars restart automatically.
api=$(inner ps -a -q api)
state=$(docker exec "$daemon" docker inspect --format '{{.State.Running}}' "$api")
[ "$state" = false ]
echo 'PASS API remains stopped after daemon reboot; no pre-firewall startup race'
inner ps -a
recover
echo "PASS isolated Docker daemon reboot and full-stack recovery; evidence: $work"
