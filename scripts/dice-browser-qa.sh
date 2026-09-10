#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_key="$(printf '%s' "$repo_dir" | cksum | awk '{print $1}')"
backend_port="${DICE_QA_BACKEND_PORT:-8000}"
frontend_port="${DICE_QA_FRONTEND_PORT:-8080}"
for port in "$backend_port" "$frontend_port"; do
  [[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || {
    printf 'Dice QA ports must be integers from 1024 through 65535.\n' >&2
    exit 2
  }
done
state_dir="${XDG_RUNTIME_DIR:-/tmp}/cozy-commons-dice-browser-qa-${UID}-${repo_key}-${backend_port}-${frontend_port}"
backend_url="http://127.0.0.1:$backend_port"
frontend_url="http://127.0.0.1:$frontend_port"
browser_url="http://localhost:$frontend_port/dice/live"

usage() { printf 'Usage: scripts/dice-browser-qa.sh <start|status|scenario|fuzz|stop> [scenario options]\n'; }
record_pid() {
  local name="$1" pid="$2"
  printf '%s\n' "$pid" >"$state_dir/$name.pid"
  ps -o lstart= -p "$pid" | sed 's/^ *//; s/ *$//' >"$state_dir/$name.started"
  source_fingerprint >"$state_dir/$name.source"
}
source_fingerprint() {
  local path hash
  {
    git -C "$repo_dir" rev-parse HEAD
    git -C "$repo_dir" diff --no-ext-diff --binary HEAD -- backend frontend scripts
    git -C "$repo_dir" ls-files --others --exclude-standard -- backend frontend scripts |
      while IFS= read -r path; do
        # Dev servers may remove their own transient files between discovery
        # and hashing. They are not source inputs and must not break ownership.
        [[ -f "$repo_dir/$path" ]] || continue
        hash="$(git -C "$repo_dir" hash-object "$repo_dir/$path" 2>/dev/null)" || continue
        printf '%s %s\n' "$path" "$hash"
      done
  } | shasum -a 256 | awk '{print $1}'
}
owned_pid() {
  local name="$1" pid group command_line expected started recorded_started
  [[ -r "$state_dir/$name.pid" && -r "$state_dir/$name.started" && -r "$state_dir/$name.source" ]] || return 1
  read -r pid <"$state_dir/$name.pid"
  kill -0 "$pid" 2>/dev/null || return 1
  read -r recorded_started <"$state_dir/$name.started"
  started="$(ps -o lstart= -p "$pid" | sed 's/^ *//; s/ *$//')"
  [[ -n "$started" && "$started" == "$recorded_started" ]] || return 1
  group="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  command_line="$(ps -o command= -p "$pid")"
  case "$name" in
    backend) expected='uvicorn main:app' ;;
    frontend) expected='npm run dev' ;;
    *) return 1 ;;
  esac
  [[ "$group" == "$pid" ]] || return 1
  [[ "$command_line" == *"$expected"* || "$command_line" == *"start-local-dice-$name.sh"* ]] || return 1
  printf '%s\n' "$pid"
}
current_owned_pid() {
  local name="$1" pid recorded_source
  pid="$(owned_pid "$name")" || return 1
  read -r recorded_source <"$state_dir/$name.source"
  [[ "$recorded_source" == "$(source_fingerprint)" ]] || return 1
  printf '%s\n' "$pid"
}
launch_detached() {
  python3 - "$1" "$2" <<'PY'
import subprocess
import sys

log_path, launcher = sys.argv[1:]
with open(log_path, "ab", buffering=0) as log:
    process = subprocess.Popen(
        [launcher], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
print(process.pid)
PY
}
stop_one() {
  local name="$1" pid attempt
  if pid="$(owned_pid "$name")"; then
    # Each launcher owns a new session, so its npm/uvicorn children can be
    # stopped together without touching unrelated development processes.
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    for ((attempt = 0; attempt < 50; attempt++)); do
      if ! kill -0 -- "-$pid" 2>/dev/null && ! kill -0 "$pid" 2>/dev/null; then break; fi
      sleep 0.1
    done
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$state_dir/$name.pid" "$state_dir/$name.started" "$state_dir/$name.source"
}
stop_owned() {
  stop_one frontend
  stop_one backend
  printf 'Browser QA frontend and backend stopped; local Supabase was left running.\n'
}
is_ready() {
  curl -fsS "$backend_url/health" >/dev/null 2>&1 &&
    curl -fsS "$frontend_url/dice/live" >/dev/null 2>&1
}
show_status() {
  local supabase=stopped backend=stopped frontend=stopped feature=unknown failed=false
  if "$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" >/dev/null 2>&1; then supabase=ready; else failed=true; fi
  if curl -fsS "$backend_url/health" >/dev/null 2>&1; then backend=ready; else failed=true; fi
  if curl -fsS "$frontend_url/dice/live" >/dev/null 2>&1; then frontend=ready; else failed=true; fi
  if [[ "$backend" == ready ]] && curl -fsS "$backend_url/openapi.json" | grep -q '"/dice/live/games"'; then feature=available; else failed=true; fi
  printf '{"supabase":"%s","backend":"%s","frontend":"%s","live_api":"%s","url":"%s"}\n' \
    "$supabase" "$backend" "$frontend" "$feature" "$browser_url"
  [[ "$failed" == false ]]
}
create_scenario() {
  if ! current_owned_pid backend >/dev/null || ! current_owned_pid frontend >/dev/null; then
    printf 'This checkout does not own a current-source browser QA stack. Run scripts/dice-browser-qa.sh start first.\n' >&2
    exit 1
  fi
  "$repo_dir/scripts/dice-live-scenario.py" \
    --api-url "$backend_url" --frontend-url "http://localhost:$frontend_port" "$@"
}
verify_feature_e2e() {
  local supabase_env anon_key token compatibility games
  supabase_env="$("$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" -o env)"
  anon_key="$(sed -n 's/^PUBLISHABLE_KEY="\(.*\)"$/\1/p' <<<"$supabase_env")"
  [[ -n "$anon_key" ]] || { printf 'Could not read the local Supabase publishable key.\n' >&2; return 1; }
  token="$(curl -fsS 'http://127.0.0.1:54321/auth/v1/token?grant_type=password' \
    -H "apikey: $anon_key" -H 'Content-Type: application/json' \
    --data '{"email":"referee@dice.local","password":"local-dice-password"}' |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
  compatibility="$(curl -fsS -X PUT "$backend_url/dice/me/features/dice_live_referee" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    --data '{"enabled":false}')"
  python3 -c 'import json,sys; assert json.load(sys.stdin) == {"dice_live_referee": {"opted_in": True, "effective": True}}' <<<"$compatibility"
  games="$(curl -fsS "$backend_url/dice/live/games" -H "Authorization: Bearer $token")"
  python3 -c 'import json,sys; assert isinstance(json.load(sys.stdin), list)' <<<"$games"
}
start_stack() {
  command -v curl >/dev/null || { printf 'Missing required command: curl\n' >&2; exit 1; }
  command -v python3 >/dev/null || { printf 'Missing required command: python3\n' >&2; exit 1; }
  if ! "$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" >/dev/null 2>&1; then
    printf 'Local Supabase is not running. Run scripts/dice-dev.sh setup once; this command will not reset it.\n' >&2
    exit 1
  fi
  mkdir -p "$state_dir"
  stop_one frontend
  stop_one backend
  if curl -fsS "$backend_url/health" >/dev/null 2>&1 || curl -fsS "$frontend_url/dice/live" >/dev/null 2>&1; then
    printf 'Ports %s or %s are occupied by a process this lifecycle does not own; leaving it untouched.\n' "$backend_port" "$frontend_port" >&2
    exit 1
  fi
  export PORT="$backend_port"
  export DICE_FRONTEND_PORT="$frontend_port"
  record_pid backend "$(launch_detached "$state_dir/backend.log" "$repo_dir/scripts/start-local-dice-backend.sh")"
  # The lifecycle owns port 8000, so do not let an ambient override point its
  # frontend at a different checkout's API. Direct frontend launches may still
  # opt into another explicit loopback port.
  export VITE_API_URL="http://localhost:$backend_port"
  record_pid frontend "$(launch_detached "$state_dir/frontend.log" "$repo_dir/scripts/start-local-dice-frontend.sh")"
  local attempt
  for ((attempt = 0; attempt < 120; attempt++)); do
    if current_owned_pid backend >/dev/null && current_owned_pid frontend >/dev/null && is_ready; then
      if verify_feature_e2e; then
        show_status
        printf 'Open: %s\n' "$browser_url"
        return 0
      fi
      break
    fi
    sleep 0.25
  done
  printf 'Browser QA stack failed its readiness check.\n' >&2
  tail -n 30 "$state_dir/backend.log" "$state_dir/frontend.log" >&2 || true
  stop_owned >&2
  return 1
}
case "${1:-}" in
  start) start_stack ;;
  status) show_status ;;
  scenario) shift; create_scenario "$@" ;;
  fuzz)
    shift
    if ! current_owned_pid backend >/dev/null || ! current_owned_pid frontend >/dev/null || ! is_ready; then
      printf 'This checkout does not own a current-source browser QA stack. Run scripts/dice-browser-qa.sh start first.\n' >&2
      exit 1
    fi
    "$repo_dir/scripts/dice-live-fuzz.py" --api-url "$backend_url" --frontend-url "http://localhost:$frontend_port" "$@"
    ;;
  stop) stop_owned ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
