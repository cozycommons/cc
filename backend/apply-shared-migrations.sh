#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

db_url="${SUPABASE_DB_URL:-}"
if [[ -z "$db_url" ]]; then
  echo "SUPABASE_DB_URL is required; refusing to deploy without migration access." >&2
  exit 1
fi

normalize_supabase_db_url() {
  local direct_url="$1"
  local pooler_host="${2:-}"

  if [[ "$direct_url" =~ ^((postgres|postgresql)://)postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432(/.*)$ ]]; then
    local scheme="${BASH_REMATCH[1]}"
    local password="${BASH_REMATCH[3]}"
    local project_ref="${BASH_REMATCH[4]}"
    local connection_tail="${BASH_REMATCH[5]}"
    if [[ ! "$pooler_host" =~ ^[a-z0-9.-]+\.pooler\.supabase\.com$ ]]; then
      echo "SUPABASE_DB_POOLER_HOST is required for an IPv4-compatible Supabase connection." >&2
      return 1
    fi
    printf '%spostgres.%s:%s@%s:5432%s\n' \
      "$scheme" "$project_ref" "$password" "$pooler_host" "$connection_tail"
    return
  fi

  printf '%s\n' "$direct_url"
}

db_url="$(normalize_supabase_db_url "$db_url" "${SUPABASE_DB_POOLER_HOST:-}")"
command -v psql >/dev/null 2>&1 || {
  echo "psql is required for the protected migration gate." >&2
  exit 1
}

read_version() {
  tr -d '[:space:]' < "$1"
}

apply_dice_migrations() {
  local baseline
  local baseline_number
  local schema_exists
  local first_version
  local migration
  local filename
  local version
  local version_number

  baseline="$(read_version "$repo_dir/migrations/PRODUCTION_SCHEMA_VERSION")"
  [[ "$baseline" =~ ^[0-9]+$ ]] || {
    echo "Invalid production schema baseline: $baseline" >&2
    exit 1
  }
  baseline_number="$((10#$baseline))"

  schema_exists="$(psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
    --command "select 1 where to_regclass('public.dice_profiles') is not null")"
  if [[ "$schema_exists" == "1" ]]; then
    first_version="$baseline_number"
  else
    first_version=0
  fi

  psql "$db_url" --set ON_ERROR_STOP=1 <<'SQL'
create table if not exists public.dice_schema_migrations (
  version integer primary key,
  applied_at timestamptz not null default now()
);
SQL

  if (( first_version == baseline_number )); then
    psql "$db_url" --set ON_ERROR_STOP=1 --command \
      "insert into public.dice_schema_migrations(version) values ($baseline_number) on conflict (version) do nothing"
  fi

  while IFS= read -r migration; do
    filename="$(basename "$migration")"
    version="${filename:0:4}"
    version_number="$((10#$version))"
    if (( version_number <= first_version )); then
      continue
    fi
    if psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
        --command "select 1 from public.dice_schema_migrations where version = $version_number" \
        | grep -q '^1$'; then
      continue
    fi
    echo "Applying $filename"
    psql "$db_url" --set ON_ERROR_STOP=1 --single-transaction \
      --file "$migration" \
      --command "insert into public.dice_schema_migrations(version) values ($version_number)"
  done < <(find "$repo_dir/migrations" -maxdepth 1 -type f \
    \( -name '[0-9][0-9][0-9][0-9]_dice_*.sql' -o -name '[0-9][0-9][0-9][0-9]_analytics_*.sql' \) | sort)

  local contract
  local contract_number
  local applied
  contract="$(read_version "$repo_dir/migrations/DICE_SCHEMA_CONTRACT_VERSION")"
  [[ "$contract" =~ ^[0-9]+$ ]] || {
    echo "Invalid Dice schema contract version: $contract" >&2
    exit 1
  }
  contract_number="$((10#$contract))"
  applied="$(psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
    --command "select 1 from public.dice_schema_migrations where version = $contract_number")"
  [[ "$applied" == "1" ]] || {
    echo "Dice schema contract $contract is not recorded as applied." >&2
    exit 1
  }
  psql "$db_url" --set ON_ERROR_STOP=1 --file "$repo_dir/migrations/dice_schema_contract.sql"
  echo "Dice migrations are applied."
}

apply_commons_migrations() {
  local migration
  local filename
  local version
  local version_number

  psql "$db_url" --set ON_ERROR_STOP=1 <<'SQL'
create table if not exists public.commons_schema_migrations (
  version integer primary key,
  applied_at timestamptz not null default now()
);
alter table public.commons_schema_migrations enable row level security;
revoke all on table public.commons_schema_migrations from public, anon, authenticated;
grant all on table public.commons_schema_migrations to service_role;
SQL

  while IFS= read -r migration; do
    filename="$(basename "$migration")"
    version="${filename:0:4}"
    version_number="$((10#$version))"
    if psql "$db_url" --tuples-only --no-align --set ON_ERROR_STOP=1 \
        --command "select 1 from public.commons_schema_migrations where version = $version_number" \
        | grep -q '^1$'; then
      continue
    fi
    echo "Applying $filename"
    psql "$db_url" --set ON_ERROR_STOP=1 --single-transaction \
      --file "$migration" \
      --command "insert into public.commons_schema_migrations(version) values ($version_number)"
  done < <(find "$repo_dir/commons/migrations" -maxdepth 1 -type f \
    -name '[0-9][0-9][0-9][0-9]_commons_*.sql' | sort)

  local contract
  local contract_number
  local applied
  contract="$(read_version "$repo_dir/commons/migrations/COMMONS_SCHEMA_CONTRACT_VERSION")"
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
    --file "$repo_dir/commons/migrations/commons_schema_contract.sql"
  echo "Commons migrations are applied."
}

if [[ "${COMMONS_ONLY:-0}" == "1" ]]; then
  apply_commons_migrations
  exit 0
fi

apply_dice_migrations
apply_commons_migrations
