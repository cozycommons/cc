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

baseline="$(tr -d '[:space:]' < "$repo_dir/backend/migrations/PRODUCTION_SCHEMA_VERSION")"
[[ "$baseline" =~ ^[0-9]+$ ]] || { echo "Invalid production schema baseline: $baseline" >&2; exit 1; }
baseline_number="$((10#$baseline))"

psql "$db_url" --set ON_ERROR_STOP=1 <<'SQL'
create table if not exists public.dice_schema_migrations (
  version integer primary key,
  applied_at timestamptz not null default now()
);
SQL

# The history table is introduced after the existing production schema. The
# attested baseline bootstraps that history exactly once; later migrations are
# applied transactionally and recorded only after success.
psql "$db_url" --set ON_ERROR_STOP=1 --command \
  "insert into public.dice_schema_migrations(version) values ($baseline_number) on conflict (version) do nothing"

while IFS= read -r migration; do
  filename="$(basename "$migration")"
  version="${filename:0:4}"
  version_number="$((10#$version))"
  if (( version_number <= baseline_number )); then
    continue
  fi
  if psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
      --command "select 1 from public.dice_schema_migrations where version = $version_number" | grep -q '^1$'; then
    continue
  fi
  echo "Applying $filename"
  psql "$db_url" --set ON_ERROR_STOP=1 --single-transaction \
    --file "$migration" \
    --command "insert into public.dice_schema_migrations(version) values ($version_number)"
done < <(find "$repo_dir/backend/migrations" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]_dice_*.sql' | sort)

SUPABASE_DB_URL="$db_url" bash "$repo_dir/scripts/verify-dice-schema.sh"
echo "Dice migrations are applied."
