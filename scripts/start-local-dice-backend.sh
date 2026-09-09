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
: "${SECRET_KEY:?Supabase status did not return SECRET_KEY}"

# Codespaces can inject repository secrets into the terminal environment. Start
# the sandbox backend from a small allowlist so unrelated integrations cannot
# inherit credentials for Twilio, OpenAI, weather providers, or production.
clean_env=(
  "HOME=$HOME"
  "PATH=$PATH"
  "LANG=${LANG:-C.UTF-8}"
  "USER=${USER:-dice-sandbox}"
  "HOST=127.0.0.1"
  "PORT=$backend_port"
  "DICE_LOCAL_HARNESS=true"
  "SUPABASE_URL=$API_URL"
  "SUPABASE_SERVICE_KEY=${SERVICE_ROLE_KEY:-$SECRET_KEY}"
  "OPENROUTER_API_KEY=disabled-for-local-dice-testing"
  "ENABLE_SCHEDULER=false"
  "CORS_EXTRA_ORIGINS=http://localhost:${frontend_port},http://127.0.0.1:${frontend_port}"
)
if [[ -n "${TMPDIR:-}" ]]; then
  clean_env+=("TMPDIR=$TMPDIR")
fi
if [[ -n "${BACKEND_VENV_DIR:-}" ]]; then
  if [[ "$BACKEND_VENV_DIR" != /* ]]; then
    printf 'BACKEND_VENV_DIR must be an absolute path.\n' >&2
    exit 1
  fi
  clean_env+=("BACKEND_VENV_DIR=$BACKEND_VENV_DIR")
fi
exec env -i "${clean_env[@]}" backend/start-local-python.sh
