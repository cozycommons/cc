#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_cli="$repo_dir/node_modules/.bin/supabase"

if [[ -x "$project_cli" ]]; then
  exec "$project_cli" "$@"
fi
if command -v supabase >/dev/null 2>&1; then
  exec supabase "$@"
fi

printf 'Missing Supabase CLI. Run npm ci from the repository root.\n' >&2
exit 1
