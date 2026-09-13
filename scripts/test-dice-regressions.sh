#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-source}"
test_database_admin_url=''
test_database_name=''

usage() {
  printf 'Usage: scripts/test-dice-regressions.sh [source|sandbox|all]\n'
}

cleanup_test_database() {
  [[ -n "$test_database_admin_url" && -n "$test_database_name" ]] || return 0
  psql "$test_database_admin_url" --no-psqlrc --set ON_ERROR_STOP=1 \
    -c "drop database if exists \"$test_database_name\" with (force)" >/dev/null
}

run_source_checks() {
  local backend_python="${BACKEND_VENV_DIR:-$repo_dir/backend/.venv}/bin/python"
  if [[ ! -x "$backend_python" ]]; then
    printf 'Backend Python is missing: %s\nRun scripts/dice-dev.sh setup first, or set BACKEND_VENV_DIR to an absolute prepared virtualenv.\n' "$backend_python" >&2
    return 1
  fi

  # Never let an ambient database URL point regression tests at a hosted
  # project. Build a disposable database beside the exact local sandbox so
  # browser-created games cannot leak into transaction tests.
  unset DB_URL DICE_TEST_DATABASE
  local supabase_env local_db_url='' bootstrap_output backend_output frontend_output
  local test_db_name="dummi_regression_${UID}_$$"
  if supabase_env="$("$repo_dir/scripts/dice-supabase.sh" status --workdir "$repo_dir" -o env 2>/dev/null)"; then
    local_db_url="$(sed -n 's/^DB_URL="\(.*\)"$/\1/p' <<<"$supabase_env")"
    if [[ "$local_db_url" == 'postgresql://postgres:postgres@127.0.0.1:54322/postgres' ]]; then
      psql "$local_db_url" --no-psqlrc --set ON_ERROR_STOP=1 \
        -c "create database \"$test_db_name\"" >/dev/null
      test_database_admin_url="$local_db_url"
      test_database_name="$test_db_name"
      trap cleanup_test_database EXIT
      export DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/$test_db_name"
      export DICE_TEST_DATABASE=1
      if ! bootstrap_output="$(DB_URL="$DB_URL" "$repo_dir/scripts/bootstrap-dice-test-db.sh" 2>&1)"; then
        printf 'Could not bootstrap the disposable Dice test database:\n%s\n' "$bootstrap_output" >&2
        return 1
      fi
      printf 'Dice transaction tests: disposable local database enabled.\n'
    else
      printf 'Dice transaction tests: skipped; local sandbox DB_URL was not exact.\n'
    fi
  else
    printf 'Dice transaction tests: skipped; local Supabase is not ready.\n'
  fi

  bash "$repo_dir/scripts/check-dice-migration-contract.sh"
  if ! backend_output="$("$backend_python" -m pytest "$repo_dir"/backend/tests/test_dice*.py -q 2>&1)"; then
    printf '%s\n' "$backend_output" >&2
    return 1
  fi
  printf 'Backend: %s\n' "$(printf '%s\n' "$backend_output" | tail -1)"
  if ! frontend_output="$(npm --prefix "$repo_dir/frontend" test -- --run \
      src/dice sandboxConfig.test.js src/runtimeConfig.test.js --reporter=dot 2>&1)"; then
    printf '%s\n' "$frontend_output" >&2
    return 1
  fi
  printf 'Frontend: %s\n' "$(printf '%s\n' "$frontend_output" | grep 'Tests  .*passed' | tail -1 | sed 's/^ *//')"
}

run_sandbox_checks() {
  "$repo_dir/scripts/dice-browser-qa.sh" status
  "$repo_dir/scripts/dice-browser-qa.sh" scenario --score 1-0 --target 1
  "$repo_dir/scripts/dice-browser-qa.sh" scenario --score 4-5
  "$repo_dir/scripts/dice-browser-qa.sh" scenario --score 6-5 --target 5 --win-by 1
  "$repo_dir/scripts/dice-browser-qa.sh" scenario --score 25-23 --target 5 --win-by 2
}

case "$mode" in
  source) run_source_checks ;;
  sandbox) run_sandbox_checks ;;
  all)
    run_source_checks
    run_sandbox_checks
    ;;
  help|-h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

printf 'Dice regression suite passed (%s).\n' "$mode"
