#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
mkdir "$test_dir/bin"
ln -s "$repo_dir/scripts/test-fixtures/mock-commons-psql.sh" "$test_dir/bin/psql"

direct='postgresql://postgres:p%40ss@db.exampleprojectref.supabase.co:5432/postgres?sslmode=require'
pooler_host='aws-0-us-east-2.pooler.supabase.com'

export PSQL_LOG="$test_dir/fresh.log"
: > "$PSQL_LOG"
: > "$PSQL_LOG.applied"
PATH="$test_dir/bin:$PATH" \
SUPABASE_DB_URL="$direct" \
SUPABASE_DB_POOLER_HOST="$pooler_host" \
MOCK_EXISTING_SCHEMA=0 \
  bash "$repo_dir/scripts/apply-commons-migrations.sh" >/dev/null

for version in 0001 0002 0003 0004 0005 0006 0007 0008 0009; do
  grep -q "${version}_commons_" "$PSQL_LOG"
done
grep -q 'commons_schema_contract.sql' "$PSQL_LOG"

export PSQL_LOG="$test_dir/existing.log"
: > "$PSQL_LOG"
: > "$PSQL_LOG.applied"
PATH="$test_dir/bin:$PATH" \
SUPABASE_DB_URL="$direct" \
SUPABASE_DB_POOLER_HOST="$pooler_host" \
MOCK_EXISTING_SCHEMA=1 \
  bash "$repo_dir/scripts/apply-commons-migrations.sh" >/dev/null

if grep -Eq '/000[1-7]_commons_.*\.sql' "$PSQL_LOG"; then
  echo 'An existing Commons schema must not replay applied migrations.' >&2
  exit 1
fi
grep -q 'commons_schema_contract.sql' "$PSQL_LOG"

echo 'Commons migration runner tests passed.'
