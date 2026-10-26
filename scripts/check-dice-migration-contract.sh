#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
contract="$(tr -d '[:space:]' < "$repo_dir/backend/migrations/DICE_SCHEMA_CONTRACT_VERSION")"
[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Dice schema contract version: $contract" >&2
  exit 1
}

latest="$(find "$repo_dir/backend/migrations" -maxdepth 1 -type f \
  \( -name '[0-9][0-9][0-9][0-9]_dice_*.sql' -o -name '[0-9][0-9][0-9][0-9]_analytics_*.sql' \) -exec basename {} \; \
  | sed -E 's/^([0-9]{4}).*/\1/' | sort -n | tail -1)"
[[ "$latest" =~ ^[0-9]{4}$ ]] || {
  echo 'No Dice migrations found.' >&2
  exit 1
}

latest_number="$((10#$latest))"
contract_number="$((10#$contract))"

# Every numbered SQL migration must belong to a runner-owned family. This makes
# adding a new family an explicit change instead of silently omitting it in CI.
while IFS= read -r migration; do
  filename="$(basename "$migration")"
  case "$filename" in
    [0-9][0-9][0-9][0-9]_dice_*.sql|[0-9][0-9][0-9][0-9]_analytics_*.sql|[0-9][0-9][0-9][0-9]_beli_*.sql|[0-9][0-9][0-9][0-9]_venmo_*.sql) ;;
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

echo "Incoming releases require individual migration receipts and apply pending files before HTTP (latest: $latest)."
