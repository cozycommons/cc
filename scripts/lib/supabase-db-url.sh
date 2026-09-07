#!/usr/bin/env bash

# Supabase's direct database hostname is IPv6-only. GitHub-hosted runners do
# not currently have an IPv6 route, so normalize a Direct URI to an explicitly
# configured IPv4-capable session pooler. Already-pooled and non-Supabase URLs
# are left unchanged.
normalize_supabase_db_url() {
  local db_url="$1"
  local pooler_host="${2:-}"

  if [[ "$db_url" =~ ^((postgres|postgresql)://)postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432(/.*)$ ]]; then
    local scheme="${BASH_REMATCH[1]}"
    local password="${BASH_REMATCH[3]}"
    local project_ref="${BASH_REMATCH[4]}"
    local connection_tail="${BASH_REMATCH[5]}"
    if [[ ! "$pooler_host" =~ ^[a-z0-9.-]+\.pooler\.supabase\.com$ ]]; then
      echo "SUPABASE_DB_POOLER_HOST is required for an IPv4-compatible Supabase connection." >&2
      return 1
    fi
    printf '%spostgres.%s:%s@%s:5432%s\n' \
      "$scheme" \
      "$project_ref" \
      "$password" \
      "$pooler_host" \
      "$connection_tail"
    return
  fi

  printf '%s\n' "$db_url"
}
