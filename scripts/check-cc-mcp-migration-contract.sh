#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
migration_dir="$repo_dir/backend/cc_mcp/migrations"
contract="$(tr -d '[:space:]' < "$migration_dir/CC_MCP_SCHEMA_CONTRACT_VERSION")"

[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Cozy Commons MCP schema contract version: $contract" >&2
  exit 1
}

latest="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_cc_mcp_*.sql' -exec basename {} \; \
  | sed -E 's/^([0-9]{4}).*/\1/' | sort -n | tail -1)"
[[ "$latest" =~ ^[0-9]{4}$ ]] || {
  echo 'No Cozy Commons MCP migrations found.' >&2
  exit 1
}

duplicates="$(find "$migration_dir" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_cc_mcp_*.sql' -exec basename {} \; \
  | cut -c1-4 | sort | uniq -d)"
[[ -z "$duplicates" ]] || {
  echo "Duplicate Cozy Commons MCP migration versions: $duplicates" >&2
  exit 1
}

latest_number="$((10#$latest))"
contract_number="$((10#$contract))"
if (( contract_number != latest_number )); then
  echo "Cozy Commons MCP schema contract $contract must match latest migration $latest." >&2
  exit 1
fi
[[ -f "$migration_dir/cc_mcp_schema_contract.sql" ]] || {
  echo 'Cozy Commons MCP schema contract SQL is missing.' >&2
  exit 1
}
grep -q 'cc_mcp' "$repo_dir/backend/migration_runner.py" || {
  echo 'Migration runner does not declare the Cozy Commons MCP family.' >&2
  exit 1
}

echo "Cozy Commons MCP migration contract is aligned at $contract."
