#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/scripts/lib/supabase-db-url.sh"

direct='postgresql://postgres:p%40ss@db.exampleprojectref.supabase.co:5432/postgres?sslmode=require'
expected='postgresql://postgres.exampleprojectref:p%40ss@aws-0-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require'
actual="$(normalize_supabase_db_url "$direct" 'aws-0-us-east-2.pooler.supabase.com')"
[[ "$actual" == "$expected" ]]

pooled='postgresql://postgres.exampleprojectref:p%40ss@aws-0-us-east-2.pooler.supabase.com:5432/postgres'
[[ "$(normalize_supabase_db_url "$pooled" '')" == "$pooled" ]]

if normalize_supabase_db_url "$direct" '' >/dev/null 2>&1; then
  echo 'Direct Supabase URLs must require an explicit pooler host.' >&2
  exit 1
fi

test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
export PSQL_LOG="$test_dir/psql.log"
contract="$(tr -d '[:space:]' < "$repo_dir/backend/migrations/DICE_SCHEMA_CONTRACT_VERSION")"
contract_number="$((10#$contract))"
contract_migration="$(basename "$(find "$repo_dir/backend/migrations" -maxdepth 1 -type f -name "${contract}_dice_*.sql" -print -quit)")"
[[ -n "$contract_migration" ]]
export contract_number contract_migration
psql() {
  printf '%q ' "$@" >> "$PSQL_LOG"
  printf '\n' >> "$PSQL_LOG"
  if [[ "$*" == *"select 1 from public.dice_schema_migrations where version = $contract_number"* ]] \
     && grep -q "$contract_migration" "$PSQL_LOG"; then
    printf '1\n'
  fi
}
export -f psql

SUPABASE_DB_URL="$direct" \
SUPABASE_DB_POOLER_HOST='aws-0-us-east-2.pooler.supabase.com' \
  bash "$repo_dir/scripts/apply-dice-migrations.sh" >/dev/null

if grep -Eq '/00(0[1-9]|[1-3][0-9]|4[0-2])_dice_.*\.sql' "$PSQL_LOG"; then
  echo 'The production baseline must prevent historical migrations from being replayed.' >&2
  exit 1
fi

migration_call="$(grep '0043_dice_game_player_group_stage_scope.sql' "$PSQL_LOG")"
[[ "$migration_call" == *'--file'* ]]
[[ "$migration_call" == *'--command'*'insert'* ]]

latest_line="$(grep -n "$contract_migration" "$PSQL_LOG" | cut -d: -f1)"
contract_line="$(grep -n 'dice_schema_contract.sql' "$PSQL_LOG" | cut -d: -f1)"
[[ -n "$latest_line" && -n "$contract_line" && "$contract_line" -gt "$latest_line" ]]

echo 'Supabase migration runner tests passed.'
