#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/scripts/lib/supabase-db-url.sh"

db_url="${SUPABASE_DB_URL:-}"
[[ -n "$db_url" ]] || {
  echo "SUPABASE_DB_URL is required for Commons schema attestation." >&2
  exit 1
}
db_url="$(normalize_supabase_db_url "$db_url" "${SUPABASE_DB_POOLER_HOST:-}")"

contract="$(tr -d '[:space:]' < "$repo_dir/backend/commons/migrations/COMMONS_SCHEMA_CONTRACT_VERSION")"
[[ "$contract" =~ ^[0-9]+$ ]] || {
  echo "Invalid Commons schema contract version: $contract" >&2
  exit 1
}
contract_number="$((10#$contract))"

applied="$(psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
  --command "select 1 from public.commons_schema_migrations where version = $contract_number")"
[[ "$applied" == "1" ]] || {
  echo "Commons schema contract $contract is not recorded as applied." >&2
  exit 1
}

psql "$db_url" --set ON_ERROR_STOP=1 \
  --file "$repo_dir/backend/commons/migrations/commons_schema_contract.sql"
echo "Commons schema contract $contract is satisfied."
