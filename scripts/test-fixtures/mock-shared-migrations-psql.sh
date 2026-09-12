#!/usr/bin/env bash
set -euo pipefail

: "${PSQL_LOG:?PSQL_LOG is required}"
: "${PSQL_APPLIED:?PSQL_APPLIED is required}"

printf '%q ' "$@" >> "$PSQL_LOG"
printf '\n' >> "$PSQL_LOG"

if [[ "$*" == *"to_regclass('public.dice_profiles')"* ]]; then
  if [[ "${MOCK_EXISTING_SCHEMA:-}" == "1" ]]; then
    printf '1\n'
  fi
  exit 0
fi

if [[ "$*" == *"select 1 from public.dice_schema_migrations where version ="* ]]; then
  if [[ "$*" =~ where\ version\ =\ ([0-9]+) ]] \
    && grep -qx "dice:${BASH_REMATCH[1]}" "$PSQL_APPLIED"; then
    printf '1\n'
    exit 0
  fi
  exit 0
fi

if [[ "$*" == *"select 1 from public.commons_schema_migrations where version ="* ]]; then
  for version in 1 2 3 4 5 6 7; do
    if [[ "$*" == *"where version = $version"* ]] && grep -qx "commons:$version" "$PSQL_APPLIED"; then
      printf '1\n'
      exit 0
    fi
  done
  exit 0
fi

if [[ "$*" == *"insert into public.dice_schema_migrations"* ]]; then
  if [[ "$*" =~ values\ \(([0-9]+)\) ]]; then
    printf 'dice:%s\n' "${BASH_REMATCH[1]}" >> "$PSQL_APPLIED"
    exit 0
  fi
fi

if [[ "$*" == *"insert into public.commons_schema_migrations"* ]]; then
  for version in 1 2 3 4 5 6 7; do
    if [[ "$*" == *"values ($version)"* ]]; then
      printf 'commons:%s\n' "$version" >> "$PSQL_APPLIED"
      exit 0
    fi
  done
fi
