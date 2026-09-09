#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
eval "$("$repo_dir/scripts/dice-supabase.sh" status -o env)"

backend_port="${DICE_BACKEND_PORT:-8000}"
frontend_port="${DICE_FRONTEND_PORT:-8080}"
case "$backend_port" in ''|*[!0-9]*) printf 'DICE_BACKEND_PORT must be a TCP port number.\n' >&2; exit 1 ;; esac
case "$frontend_port" in ''|*[!0-9]*) printf 'DICE_FRONTEND_PORT must be a TCP port number.\n' >&2; exit 1 ;; esac
if [ "$backend_port" -lt 1 ] || [ "$backend_port" -gt 65535 ] || [ "$frontend_port" -lt 1 ] || [ "$frontend_port" -gt 65535 ]; then
  printf 'DICE_BACKEND_PORT and DICE_FRONTEND_PORT must be between 1 and 65535.\n' >&2
  exit 1
fi

if [[ "${API_URL:-}" != "http://127.0.0.1:54321" ]]; then
  printf 'Refusing to start the local harness with Supabase URL: %s\n' "${API_URL:-<unset>}" >&2
  exit 1
fi
: "${PUBLISHABLE_KEY:?Supabase status did not return PUBLISHABLE_KEY}"

export VITE_API_URL="http://localhost:${backend_port}"
export VITE_SUPABASE_URL="$API_URL"
export VITE_SUPABASE_ANON_KEY="$PUBLISHABLE_KEY"
export VITE_DICE_LOCAL_HARNESS=true
export VITE_LOCAL_DICE_EMAIL=referee@dice.local
export VITE_LOCAL_DICE_PASSWORD=local-dice-password
cd frontend
if command -v npm >/dev/null 2>&1; then
  exec npm run dev -- --host 0.0.0.0 --port "$frontend_port"
fi
mise_bin="$HOME/.local/bin/mise"
if [[ -x "$mise_bin" ]]; then
  exec "$mise_bin" exec -- npm run dev -- --host 0.0.0.0 --port "$frontend_port"
fi
printf 'Missing required command: npm\n' >&2
exit 1
