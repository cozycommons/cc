#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_dir"

eval "$("$repo_dir/scripts/dice-supabase.sh" status -o env)"
: "${DB_URL:?Supabase status did not return DB_URL}"
if [[ "${API_URL:-}" != "http://127.0.0.1:54321" ||
      "$DB_URL" != "postgresql://postgres:postgres@127.0.0.1:54322/postgres" ]]; then
  printf 'Refusing reset outside the expected local Supabase stack.\n' >&2
  exit 1
fi

"$repo_dir/scripts/dice-supabase.sh" db reset --local --no-seed

for migration in backend/migrations/*_dice_*.sql; do
  printf 'Applying %s\n' "$migration"
  psql "$DB_URL" --set ON_ERROR_STOP=1 --single-transaction --file "$migration"
done
psql "$DB_URL" --set ON_ERROR_STOP=1 --file supabase/dice-seed.sql

psql "$DB_URL" --set ON_ERROR_STOP=1 --file supabase/dice-local-grants.sql

# db reset restarts Auth; refresh Kong's upstream DNS entry before browser use.
kong_container="$(
  docker ps \
    --filter "publish=54321" \
    --filter "name=supabase_kong_" \
    --format '{{.Names}}'
)"
if [[ -z "$kong_container" || "$kong_container" == *$'\n'* ]]; then
  printf 'Could not identify the local Supabase Kong container on port 54321.\n' >&2
  exit 1
fi
docker restart "$kong_container" >/dev/null
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused --retry-all-errors \
  http://127.0.0.1:54321/auth/v1/health >/dev/null

profile_count="$(
  psql "$DB_URL" --tuples-only --no-align \
    --command "select count(*) from public.dice_profiles"
)"
if [[ "$profile_count" != "5" ]]; then
  printf 'Local seed verification failed: expected 5 Dice profiles, got %s\n' \
    "$profile_count" >&2
  exit 1
fi

printf 'Local Dice database is ready with synthetic data only.\n'
