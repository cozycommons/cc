#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
migration_dir="$repo_dir/backend/commons/migrations"
contract="$(tr -d '[:space:]' < "$migration_dir/COMMONS_SCHEMA_CONTRACT_VERSION")"

[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Commons schema contract version: $contract" >&2
  exit 1
}

latest="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_commons_*.sql' -exec basename {} \; \
  | sed -E 's/^([0-9]{4}).*/\1/' | sort -n | tail -1)"
[[ "$latest" =~ ^[0-9]{4}$ ]] || {
  echo 'No Commons migrations found.' >&2
  exit 1
}

duplicates="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_commons_*.sql' -exec basename {} \; \
  | cut -c1-4 | sort | uniq -d)"
[[ -z "$duplicates" ]] || {
  echo "Duplicate Commons migration versions: $duplicates" >&2
  exit 1
}

latest_number="$((10#$latest))"
contract_number="$((10#$contract))"
if (( contract_number != latest_number )); then
  echo "Commons schema contract $contract must match latest migration $latest." >&2
  exit 1
fi

echo "Commons migration contract is aligned at $contract."
