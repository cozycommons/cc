#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_key="$(printf '%s' "$repo_dir" | cksum | awk '{print $1}')"
state_dir="${XDG_RUNTIME_DIR:-/tmp}/cozy-commons-dice-browser-qa-${UID}-${repo_key}"
backend_url="http://127.0.0.1:8000"
frontend_url="http://127.0.0.1:8080"
browser_url="http://localhost:8080/dice/live"

usage() { printf 'Usage: scripts/dice-browser-qa.sh <start|status|stop>\n'; }
record_pid() {
  printf '%s\n' "$2" >"$state_dir/$1.pid"
}
owned_pid() {
  local name="$1" pid group command_line expected
  [[ -r "$state_dir/$name.pid" ]] || return 1
  read -r pid <"$state_dir/$name.pid"
  kill -0 "$pid" 2>/dev/null || return 1
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
  rm -f "$state_dir/$name.pid"
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
verify_feature_e2e() {
  local supabase_env anon_key token features games
  supabase_env="$("$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" -o env)"
  anon_key="$(sed -n 's/^PUBLISHABLE_KEY="\(.*\)"$/\1/p' <<<"$supabase_env")"
  [[ -n "$anon_key" ]] || { printf 'Could not read the local Supabase publishable key.\n' >&2; return 1; }
  token="$(curl -fsS 'http://127.0.0.1:54321/auth/v1/token?grant_type=password' \
    -H "apikey: $anon_key" -H 'Content-Type: application/json' \
    --data '{"email":"referee@dice.local","password":"local-dice-password"}' |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
  features="$(curl -fsS -X PUT "$backend_url/dice/me/features/dice_live_referee" \
    -H "Authorization: Bearer $token" -H 'Content-Type: application/json' --data '{"enabled":true}')"
  python3 -c 'import json,sys; s=json.load(sys.stdin)["dice_live_referee"]; assert s == {"opted_in": True, "effective": True}, s' <<<"$features"
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
    printf 'Ports 8000 or 8080 are occupied by a process this lifecycle does not own; leaving it untouched.\n' >&2
    exit 1
  fi
  record_pid backend "$(launch_detached "$state_dir/backend.log" "$repo_dir/scripts/start-local-dice-backend.sh")"
  record_pid frontend "$(launch_detached "$state_dir/frontend.log" "$repo_dir/scripts/start-local-dice-frontend.sh")"
  local attempt
  for ((attempt = 0; attempt < 120; attempt++)); do
    if is_ready; then
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
  stop) stop_owned ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
