#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
baseline="$(tr -d '[:space:]' < "$repo_dir/backend/migrations/PRODUCTION_SCHEMA_VERSION")"
contract="$(tr -d '[:space:]' < "$repo_dir/backend/migrations/DICE_SCHEMA_CONTRACT_VERSION")"
[[ "$baseline" =~ ^[0-9]+$ ]] || {
  echo "Invalid production migration baseline: $baseline" >&2
  exit 1
}
[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Dice schema contract version: $contract" >&2
  exit 1
}

latest="$(find "$repo_dir/backend/migrations" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_dice_*.sql' -exec basename {} \; \
  | sed -E 's/^([0-9]{4}).*/\1/' | sort -n | tail -1)"
[[ "$latest" =~ ^[0-9]{4}$ ]] || {
  echo 'No Dice migrations found.' >&2
  exit 1
}

baseline_number="$((10#$baseline))"
latest_number="$((10#$latest))"
contract_number="$((10#$contract))"
if (( latest_number < baseline_number )); then
  echo "Migration baseline $baseline has no matching repository history (latest is $latest)." >&2
  exit 1
fi

if (( contract_number != latest_number )); then
  echo "Dice schema contract $contract must be reviewed and advanced with latest migration $latest." >&2
  exit 1
fi

if (( latest_number > baseline_number )); then
  echo "Migrations after baseline $baseline are pending deployment through the protected main migration job (latest: $latest)."
else
  echo "Migration baseline and repository history are aligned at $baseline."
fi
