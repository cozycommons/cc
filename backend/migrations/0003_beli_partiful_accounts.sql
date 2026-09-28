-- Partiful app: per-user account storage.
-- One row per friend: encrypted Firebase refresh token + uid, plus the hashed
-- personal API token. Plaintext tokens are never stored; the token is shown
-- once at onboarding.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.partiful_accounts (
  id uuid primary key default gen_random_uuid(),
  label text not null default 'partiful',
  refresh_token_enc text not null,
  uid_enc text not null,
  token_hash text not null unique,
  token_prefix text not null,
  created_at timestamptz not null default now()
);

alter table public.partiful_accounts enable row level security;
revoke all on public.partiful_accounts from public, anon, authenticated;
grant select, insert, update on public.partiful_accounts to service_role;
