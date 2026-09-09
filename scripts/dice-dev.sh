#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mise_bin="$HOME/.local/bin/mise"
supabase_command=("$repo_dir/scripts/dice-supabase.sh")

usage() {
  cat <<'EOF'
Usage: scripts/dice-dev.sh <command>

Commands:
  install     Install locked root, frontend, and backend dependencies
  doctor      Check required tools, versions, and local service ports
  verify      Run repository checks without starting services or resetting data
  setup       Start local Supabase and rebuild the synthetic Dice database
  local       Run the backend and frontend against local Supabase
  codespace   Run the same harness behind a private Codespaces URL
  reset       Rebuild only the local synthetic Dice database
  status      Check Supabase, backend, and frontend health
  stop        Stop the local Supabase stack
  production  Run the frontend against production (requires DICE_ALLOW_PRODUCTION=1)
EOF
}

install_dependencies() {
  cd "$repo_dir"
  resolve_npm
  "${npm_command[@]}" ci
  cd "$repo_dir/frontend"
  "${npm_command[@]}" ci
  "$repo_dir/backend/start-local-python.sh" --setup-only
}

show_doctor() {
  local failed=false
  local command_name
  for command_name in docker psql curl; do
    if command -v "$command_name" >/dev/null 2>&1; then
      printf '%-10s %s\n' "$command_name:" "$(command -v "$command_name")"
    else
      printf '%-10s missing\n' "$command_name:" >&2
      failed=true
    fi
  done
  local python_bin=""
  if command -v python3.12 >/dev/null 2>&1; then
    python_bin="$(command -v python3.12)"
  elif command -v python3.13 >/dev/null 2>&1; then
    python_bin="$(command -v python3.13)"
  fi
  if [[ -n "$python_bin" ]]; then
    printf '%-10s %s (%s)\n' 'python:' "$python_bin" "$("$python_bin" --version 2>&1)"
  else
    printf '%-10s missing Python 3.12 or 3.13\n' 'python:' >&2
    failed=true
  fi
  if command -v npm >/dev/null 2>&1 || [[ -x "$mise_bin" ]]; then
    resolve_npm
    printf '%-10s %s\n' 'npm:' "$("${npm_command[@]}" --version)"
    local node_version
    if command -v node >/dev/null 2>&1; then
      node_version="$(node --version)"
    else
      node_version="$("$mise_bin" exec -- node --version)"
    fi
    printf '%-10s %s\n' 'node:' "$node_version"
    case "$node_version" in
      v22.*) ;;
      *)
        printf 'Node 22 is required for parity with CI and production.\n' >&2
        failed=true
        ;;
    esac
  else
    printf '%-10s missing\n' 'npm:' >&2
    failed=true
  fi
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    printf 'Docker:    ready\n'
  else
    printf 'Docker:    unavailable\n' >&2
    failed=true
  fi
  printf 'Required local ports: 54321-54327, %s, %s\n' "${DICE_BACKEND_PORT:-8000}" "${DICE_FRONTEND_PORT:-8080}"
  [[ "$failed" == false ]]
}

run_verification() {
  resolve_npm
  cd "$repo_dir/frontend"
  "${npm_command[@]}" test -- --run
  "${npm_command[@]}" run lint
  "${npm_command[@]}" run build:check
  cd "$repo_dir"
  "$repo_dir/scripts/check-dice-migration-contract.sh"
  bash -n "$repo_dir"/scripts/*.sh "$repo_dir"/backend/*.sh
  if [[ -x "$repo_dir/backend/.venv/bin/python" ]]; then
    PYTHONPATH="$repo_dir/backend" \
      "$repo_dir/backend/.venv/bin/python" -m pytest "$repo_dir/backend/tests" -q
  else
    printf 'Backend virtualenv is missing. Run scripts/dice-dev.sh install first.\n' >&2
    return 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

resolve_npm() {
  if command -v npm >/dev/null 2>&1; then
    npm_command=(npm)
  elif [[ -x "$mise_bin" ]]; then
    npm_command=("$mise_bin" exec -- npm)
  else
    printf 'Missing required command: npm\n' >&2
    exit 1
  fi
}

require_local_supabase() {
  if ! "${supabase_command[@]}" status --workdir "$repo_dir" >/dev/null 2>&1; then
    printf 'Local Supabase is not running. Run scripts/dice-dev.sh setup first.\n' >&2
    exit 1
  fi
}

codespaces_url() {
  if [[ "${CODESPACES:-}" != "true" ||
        ! "${CODESPACE_NAME:-}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ||
        ! "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ||
        "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" == *..* ]]; then
    printf 'Missing or invalid GitHub Codespaces host metadata.\n' >&2
    return 1
  fi
  printf 'https://%s-8080.%s' \
    "$CODESPACE_NAME" "$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
}

run_harness() {
  local dice_url="$1"
  require_local_supabase

  local pids=()
  cleanup() {
    if ((${#pids[@]})); then
      kill "${pids[@]}" 2>/dev/null || true
      wait "${pids[@]}" 2>/dev/null || true
    fi
  }
  trap cleanup INT TERM

  "$repo_dir/scripts/start-local-dice-backend.sh" &
  pids+=("$!")
  "$repo_dir/scripts/start-local-dice-frontend.sh" &
  pids+=("$!")

  printf 'Dice sandbox:         %s/dice\n' "$dice_url"
  printf 'Supabase Studio:       http://localhost:54323\n'
  printf 'Press Ctrl-C to stop the frontend and backend.\n'
  local wait_status=0
  local finished_pid=""
  while [[ -z "$finished_pid" ]]; do
    local pid
    for pid in "${pids[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        finished_pid="$pid"
        break
      fi
    done
    [[ -n "$finished_pid" ]] || sleep 1
  done
  wait "$finished_pid" || wait_status=$?
  cleanup
  trap - INT TERM
  return "$wait_status"
}

show_status() {
  local failed=false
  local backend_port="${DICE_BACKEND_PORT:-8000}"
  local frontend_port="${DICE_FRONTEND_PORT:-8080}"
  if "${supabase_command[@]}" status --workdir "$repo_dir" >/dev/null 2>&1; then
    printf 'Supabase: ready\n'
  else
    printf 'Supabase: stopped\n'
    failed=true
  fi
  if curl -fsS "http://127.0.0.1:${backend_port}/health" >/dev/null 2>&1; then
    printf 'Backend:  ready\n'
  else
    printf 'Backend:  stopped\n'
    failed=true
  fi
  if curl -fsS "http://127.0.0.1:${frontend_port}/dice" >/dev/null 2>&1; then
    printf 'Frontend: ready\n'
  else
    printf 'Frontend: stopped\n'
    failed=true
  fi
  if [[ "${CODESPACES:-}" == "true" ]]; then
    printf 'Browser:  %s/dice\n' "$(codespaces_url)"
  else
    printf 'Browser:  http://localhost:%s/dice\n' "$frontend_port"
  fi
  [[ "$failed" == false ]]
}

run_production() {
  if [[ "${CODESPACES:-}" == "true" ]]; then
    printf 'Production mode is prohibited inside GitHub Codespaces.\n' >&2
    exit 1
  fi
  if [[ "${DICE_ALLOW_PRODUCTION:-}" != "1" ]]; then
    cat >&2 <<'EOF'
Production mode uses real accounts and real data, and Dice UI actions can write
to production. Re-run with DICE_ALLOW_PRODUCTION=1 only when that is intended.
EOF
    exit 1
  fi

  cd "$repo_dir/frontend"
  resolve_npm
  if [[ ! -d node_modules ]]; then
    "${npm_command[@]}" ci
  fi
  exec "${npm_command[@]}" run dev -- --mode production --host 127.0.0.1 --port 8080
}

case "${1:-}" in
  install)
    install_dependencies
    ;;
  doctor)
    show_doctor
    ;;
  verify)
    run_verification
    ;;
  setup)
    require_command docker
    require_command psql
    require_command curl
    install_dependencies
    cd "$repo_dir"
    "${supabase_command[@]}" start
    exec "$repo_dir/scripts/reset-local-dice-db.sh"
    ;;
  local)
    if [[ "${CODESPACES:-}" == "true" ]]; then
      printf 'Use scripts/dice-dev.sh codespace inside GitHub Codespaces.\n' >&2
      exit 2
    fi
    run_harness "http://localhost:${DICE_FRONTEND_PORT:-8080}"
    ;;
  codespace)
    run_harness "$(codespaces_url)"
    ;;
  reset)
    require_local_supabase
    exec "$repo_dir/scripts/reset-local-dice-db.sh"
    ;;
  status)
    show_status
    ;;
  stop)
    exec "${supabase_command[@]}" stop --workdir "$repo_dir"
    ;;
  production)
    run_production
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
