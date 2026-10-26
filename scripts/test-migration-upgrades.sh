#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_python="${BACKEND_VENV_DIR:-$repo_dir/backend/.venv}/bin/python"
[[ -x "$backend_python" ]] || { printf 'Set BACKEND_VENV_DIR to a prepared backend virtualenv.\n' >&2; exit 1; }

unset DB_URL DICE_TEST_DATABASE SUPABASE_DB_URL SUPABASE_DB_POOLER_HOST EXPECTED_SUPABASE_PROJECT
supabase_env="$("$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" -o env)"
local_db_url="$(sed -n 's/^DB_URL="\(.*\)"$/\1/p' <<<"$supabase_env")"
[[ "$local_db_url" == 'postgresql://postgres:postgres@127.0.0.1:54322/postgres' ]] || {
  printf 'Migration tests require the exact loopback Supabase database.\n' >&2
  exit 1
}
test_db_name="dummi_regression_${UID}_$$"
psql "$local_db_url" --no-psqlrc --set ON_ERROR_STOP=1 -c "create database \"$test_db_name\"" >/dev/null
cleanup() {
  psql "$local_db_url" --no-psqlrc --set ON_ERROR_STOP=1 -c "drop database \"$test_db_name\" with (force)" >/dev/null
}
trap cleanup EXIT
export DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/$test_db_name"
export DICE_TEST_DATABASE=1 DICE_REQUIRE_DATABASE_TESTS=1
export PYTHONPATH="$repo_dir/backend"
"$backend_python" -m pytest "$repo_dir/backend/tests/test_migration_runner.py" \
  "$repo_dir/backend/tests/test_migration_upgrades.py" \
  "$repo_dir/backend/tests/test_migration_convergence.py" -q "$@"
