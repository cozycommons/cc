#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
mkdir "$test_dir/bin"
ln -s "$repo_dir/scripts/test-fixtures/mock-shared-migrations-psql.sh" "$test_dir/bin/psql"

direct='postgresql://postgres:p%40ss@db.exampleprojectref.supabase.co:5432/postgres?sslmode=require'
pooler_host='aws-0-us-east-2.pooler.supabase.com'

run_case() {
  local name="$1"
  local existing="$2"
  export PSQL_LOG="$test_dir/$name.log"
  export PSQL_APPLIED="$test_dir/$name.applied"
  : > "$PSQL_LOG"
  : > "$PSQL_APPLIED"
  PATH="$test_dir/bin:$PATH" \
  SUPABASE_DB_URL="$direct" \
  SUPABASE_DB_POOLER_HOST="$pooler_host" \
  MOCK_EXISTING_SCHEMA="$existing" \
    bash "$repo_dir/backend/apply-shared-migrations.sh" >/dev/null
}

run_case fresh 0
for marker in dice:20 dice:25 dice:64 dice:78 commons:1 commons:7; do
  grep -qx "$marker" "$PSQL_APPLIED"
done

run_case existing 1
grep -qx 'dice:42' "$PSQL_APPLIED"
grep -qx 'dice:43' "$PSQL_APPLIED"
grep -qx 'dice:64' "$PSQL_APPLIED"
grep -qx 'dice:78' "$PSQL_APPLIED"
grep -qx 'commons:1' "$PSQL_APPLIED"
grep -qx 'commons:7' "$PSQL_APPLIED"
if grep -qx 'dice:20' "$PSQL_APPLIED"; then
  echo 'An existing Dice schema must not replay pre-baseline migrations.' >&2
  exit 1
fi

export PSQL_LOG="$test_dir/commons-only.log"
export PSQL_APPLIED="$test_dir/commons-only.applied"
: > "$PSQL_LOG"
: > "$PSQL_APPLIED"
PATH="$test_dir/bin:$PATH" \
SUPABASE_DB_URL="$direct" \
SUPABASE_DB_POOLER_HOST="$pooler_host" \
  bash "$repo_dir/backend/apply-commons-migrations.sh" >/dev/null
for marker in commons:1 commons:7; do
  grep -qx "$marker" "$PSQL_APPLIED"
done
if grep -q '^dice:' "$PSQL_APPLIED"; then
  echo 'Commons-only predeployment must not apply Dice migrations.' >&2
  exit 1
fi

echo 'Backend predeployment migration tests passed.'
