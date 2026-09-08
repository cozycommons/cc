#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/commons-dev.sh <command>

Commands:
  check         Validate Commons migration ownership and numbering
  migrate       Apply Commons migrations using SUPABASE_DB_URL
  local-migrate Apply Commons migrations to the local Supabase stack
  verify        Attest the applied Commons schema using SUPABASE_DB_URL
EOF
}

local_db_url() {
  eval "$($repo_dir/scripts/commons-supabase.sh status -o env)"
  : "${DB_URL:?Supabase status did not return DB_URL}"
  if [[ "${API_URL:-}" != "http://127.0.0.1:54321" ||
        "$DB_URL" != "postgresql://postgres:postgres@127.0.0.1:54322/postgres" ]]; then
    printf 'Refusing Commons migration outside the expected local Supabase stack.\n' >&2
    exit 1
  fi
  printf '%s\n' "$DB_URL"
}

case "${1:-}" in
  check)
    exec "$repo_dir/scripts/check-commons-migration-contract.sh"
    ;;
  migrate)
    exec "$repo_dir/scripts/apply-commons-migrations.sh"
    ;;
  local-migrate)
    local_url="$(local_db_url)"
    SUPABASE_DB_URL="$local_url" exec "$repo_dir/scripts/apply-commons-migrations.sh"
    ;;
  verify)
    exec "$repo_dir/scripts/verify-commons-schema.sh"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
