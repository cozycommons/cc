#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
migration_dir="$repo_dir/backend/floor_planner/migrations"
contract="$(tr -d '[:space:]' < "$migration_dir/FLOOR_PLANNER_SCHEMA_CONTRACT_VERSION")"

[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Floor Planner schema contract version: $contract" >&2
  exit 1
}

latest="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_floor_planner_*.sql' -exec basename {} \; \
  | sed -E 's/^([0-9]{4}).*/\1/' | sort -n | tail -1)"
[[ "$latest" =~ ^[0-9]{4}$ ]] || {
  echo 'No Floor Planner migrations found.' >&2
  exit 1
}

duplicates="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_floor_planner_*.sql' -exec basename {} \; \
  | cut -c1-4 | sort | uniq -d)"
[[ -z "$duplicates" ]] || {
  echo "Duplicate Floor Planner migration versions: $duplicates" >&2
  exit 1
}

latest_number="$((10#$latest))"
contract_number="$((10#$contract))"
if (( contract_number != latest_number )); then
  echo "Floor Planner schema contract $contract must match latest migration $latest." >&2
  exit 1
fi
[[ -f "$migration_dir/floor_planner_schema_contract.sql" ]] || {
  echo 'Floor Planner schema contract SQL is missing.' >&2
  exit 1
}
grep -q 'floor_planner' "$repo_dir/backend/migration_runner.py" || {
  echo 'Migration runner does not declare the Floor Planner family.' >&2
  exit 1
}

echo "Floor Planner migration contract is aligned at $contract."
