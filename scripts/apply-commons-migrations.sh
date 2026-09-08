#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/scripts/lib/supabase-db-url.sh"

db_url="${SUPABASE_DB_URL:-}"
if [[ -z "$db_url" ]]; then
  echo "SUPABASE_DB_URL is required; refusing to deploy without migration access." >&2
  exit 1
fi
db_url="$(normalize_supabase_db_url "$db_url" "${SUPABASE_DB_POOLER_HOST:-}")"

bash "$repo_dir/scripts/check-commons-migration-contract.sh"

psql "$db_url" --set ON_ERROR_STOP=1 <<'SQL'
create table if not exists public.commons_schema_migrations (
  version integer primary key,
  applied_at timestamptz not null default now()
);
alter table public.commons_schema_migrations enable row level security;
revoke all on table public.commons_schema_migrations from public, anon, authenticated;
grant all on table public.commons_schema_migrations to service_role;
SQL

while IFS= read -r migration; do
  filename="$(basename "$migration")"
  version="${filename:0:4}"
  version_number="$((10#$version))"
  if psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
      --command "select 1 from public.commons_schema_migrations where version = $version_number" \
      | grep -q '^1$'; then
    continue
  fi
  echo "Applying $filename"
  psql "$db_url" --set ON_ERROR_STOP=1 --single-transaction \
    --file "$migration" \
    --command "insert into public.commons_schema_migrations(version) values ($version_number)"
done < <(find "$repo_dir/backend/commons/migrations" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_commons_*.sql' | sort)

SUPABASE_DB_URL="$db_url" bash "$repo_dir/scripts/verify-commons-schema.sh"
echo "Commons migrations are applied."
