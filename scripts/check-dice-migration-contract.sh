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

# Every numbered SQL migration must belong to a runner-owned family. This makes
# adding a new family an explicit change instead of silently omitting it in CI.
while IFS= read -r migration; do
  filename="$(basename "$migration")"
  case "$filename" in
    [0-9][0-9][0-9][0-9]_dice_*.sql|[0-9][0-9][0-9][0-9]_analytics_*.sql) ;;
    *)
      echo "Numbered migration has no declared owner: $filename" >&2
      exit 1
      ;;
  esac
done < <(find "$repo_dir/backend/migrations" -maxdepth 1 -type f -name '[0-9][0-9][0-9][0-9]_*.sql' | sort)

duplicates="$(find "$repo_dir/backend/migrations" -maxdepth 1 -type f \
  -name '[0-9][0-9][0-9][0-9]_*.sql' -exec basename {} \; \
  | cut -c1-4 | sort | uniq -d)"
[[ -z "$duplicates" ]] || {
  echo "Duplicate migration versions: $duplicates" >&2
  exit 1
}

if (( contract_number != latest_number )); then
  echo "Dice schema contract $contract must be reviewed and advanced with latest migration $latest." >&2
  exit 1
fi

if (( latest_number > baseline_number )); then
  echo "Migrations after baseline $baseline must run through the protected pre-deploy command (latest: $latest)."
else
  echo "Migration baseline and repository history are aligned at $baseline."
fi
