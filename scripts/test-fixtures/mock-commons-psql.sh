#!/usr/bin/env bash
set -euo pipefail

: "${PSQL_LOG:?PSQL_LOG is required}"

printf '%q ' "$@" >> "$PSQL_LOG"
printf '\n' >> "$PSQL_LOG"

if [[ "$*" == *"insert into public.commons_schema_migrations"* ]]; then
  for version in 11 10 9 8 7 6 5 4 3 2 1; do
    if [[ "$*" =~ values[[:space:]]\($version\)([^0-9]|$) ]]; then
      printf '%s\n' "$version" >> "$PSQL_LOG.applied"
      exit 0
    fi
  done
fi

if [[ "$*" == *"select 1 from public.commons_schema_migrations"* ]]; then
  if [[ "${MOCK_EXISTING_SCHEMA:-}" == "1" ]]; then
    printf '1\n'
    exit 0
  fi
  for version in 11 10 9 8 7 6 5 4 3 2 1; do
    if [[ "$*" =~ where[[:space:]]version[[:space:]]=[[:space:]]$version([^0-9]|$) ]] \
      && grep -qx "$version" "$PSQL_LOG.applied"; then
      printf '1\n'
      exit 0
    fi
  done
fi
