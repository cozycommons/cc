#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
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
