#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/scripts/lib/supabase-db-url.sh"

direct='postgresql://postgres:p%40ss@db.exampleprojectref.supabase.co:5432/postgres?sslmode=require'
expected='postgresql://postgres.exampleprojectref:p%40ss@aws-0-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require'
actual="$(normalize_supabase_db_url "$direct" 'aws-0-us-east-2.pooler.supabase.com')"
[[ "$actual" == "$expected" ]]

pooled='postgresql://postgres.exampleprojectref:p%40ss@aws-0-us-east-2.pooler.supabase.com:5432/postgres'
[[ "$(normalize_supabase_db_url "$pooled" '')" == "$pooled" ]]

if normalize_supabase_db_url "$direct" '' >/dev/null 2>&1; then
  echo 'Direct Supabase URLs must require an explicit pooler host.' >&2
  exit 1
fi

echo "Supabase URL normalization tests passed."
