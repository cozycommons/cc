#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
eval "$("$repo_dir/scripts/dice-supabase.sh" status -o env)"

if [[ "${API_URL:-}" != "http://127.0.0.1:54321" ]]; then
  printf 'Refusing to start the local harness with Supabase URL: %s\n' "${API_URL:-<unset>}" >&2
  exit 1
fi
: "${PUBLISHABLE_KEY:?Supabase status did not return PUBLISHABLE_KEY}"

export VITE_API_URL=http://localhost:8000
export VITE_SUPABASE_URL="$API_URL"
export VITE_SUPABASE_ANON_KEY="$PUBLISHABLE_KEY"
export VITE_DICE_LOCAL_HARNESS=true
export VITE_LOCAL_DICE_EMAIL=referee@dice.local
export VITE_LOCAL_DICE_PASSWORD=local-dice-password
cd frontend
if command -v npm >/dev/null 2>&1; then
  exec npm run dev -- --host 0.0.0.0 --port 8080
fi
mise_bin="$HOME/.local/bin/mise"
if [[ -x "$mise_bin" ]]; then
  exec "$mise_bin" exec -- npm run dev -- --host 0.0.0.0 --port 8080
fi
printf 'Missing required command: npm\n' >&2
exit 1
