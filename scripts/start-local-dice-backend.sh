#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
backend_port="${PORT:-8000}"
frontend_port="${DICE_FRONTEND_PORT:-8080}"
if [[ ! "$backend_port" =~ ^[0-9]+$ ]] || ((backend_port < 1024 || backend_port > 65535)); then
  printf 'PORT must be an integer from 1024 through 65535.\n' >&2
  exit 1
fi
if [[ ! "$frontend_port" =~ ^[0-9]+$ ]] || ((frontend_port < 1024 || frontend_port > 65535)); then
  printf 'DICE_FRONTEND_PORT must be an integer from 1024 through 65535.\n' >&2
  exit 1
fi

eval "$("$repo_dir/scripts/dice-supabase.sh" status -o env)"

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
  "CORS_EXTRA_ORIGINS=http://localhost:$frontend_port,http://127.0.0.1:$frontend_port"
  "DICE_LOCAL_HARNESS=true"
  "SUPABASE_URL=$API_URL"
  "SUPABASE_SERVICE_KEY=${SERVICE_ROLE_KEY:-$SECRET_KEY}"
  "OPENROUTER_API_KEY=disabled-for-local-dice-testing"
  "ENABLE_SCHEDULER=false"
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
