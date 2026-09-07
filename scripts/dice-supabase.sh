#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

project_cli="$repo_dir/node_modules/.bin/supabase"
if [[ -x "$project_cli" ]]; then
  if command -v node >/dev/null 2>&1; then
    exec "$project_cli" "$@"
  fi
  mise_bin="$HOME/.local/bin/mise"
  if [[ -x "$mise_bin" ]]; then
    exec "$mise_bin" exec -- "$project_cli" "$@"
  fi
fi
if command -v supabase >/dev/null 2>&1; then
  exec supabase "$@"
fi

printf 'Missing Supabase CLI. Run npm ci from the repository root.\n' >&2
exit 1
