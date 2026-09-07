#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mise_bin="$HOME/.local/bin/mise"
supabase_command=("$repo_dir/scripts/dice-supabase.sh")

usage() {
  cat <<'EOF'
Usage: scripts/dice-dev.sh <command>

Commands:
  setup       Start local Supabase and rebuild the synthetic Dice database
  local       Run the backend and frontend against local Supabase
  codespace   Run the same harness behind a private Codespaces URL
  reset       Rebuild only the local synthetic Dice database
  status      Check Supabase, backend, and frontend health
  stop        Stop the local Supabase stack
  production  Run the frontend against production (requires DICE_ALLOW_PRODUCTION=1)
EOF
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
  wait -n "${pids[@]}" || wait_status=$?
  cleanup
  trap - INT TERM
  return "$wait_status"
}

show_status() {
  local failed=false
  if "${supabase_command[@]}" status --workdir "$repo_dir" >/dev/null 2>&1; then
    printf 'Supabase: ready\n'
  else
    printf 'Supabase: stopped\n'
    failed=true
  fi
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    printf 'Backend:  ready\n'
  else
    printf 'Backend:  stopped\n'
    failed=true
  fi
  if curl -fsS http://127.0.0.1:8080/dice >/dev/null 2>&1; then
    printf 'Frontend: ready\n'
  else
    printf 'Frontend: stopped\n'
    failed=true
  fi
  if [[ "${CODESPACES:-}" == "true" ]]; then
    printf 'Browser:  %s/dice\n' "$(codespaces_url)"
  else
    printf 'Browser:  http://localhost:8080/dice\n'
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
  setup)
    require_command docker
    require_command psql
    require_command curl
    cd "$repo_dir"
    resolve_npm
    "${npm_command[@]}" ci
    cd "$repo_dir/frontend"
    "${npm_command[@]}" ci
    "$repo_dir/backend/start-local-python.sh" --setup-only
    cd "$repo_dir"
    "${supabase_command[@]}" start
    exec "$repo_dir/scripts/reset-local-dice-db.sh"
    ;;
  local)
    if [[ "${CODESPACES:-}" == "true" ]]; then
      printf 'Use scripts/dice-dev.sh codespace inside GitHub Codespaces.\n' >&2
      exit 2
    fi
    run_harness "http://localhost:8080"
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
