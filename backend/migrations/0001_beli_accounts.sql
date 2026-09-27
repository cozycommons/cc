-- Beli app: per-user account storage.
-- One row per friend: encrypted Beli login + hashed personal API token.
-- Plaintext tokens are never stored; the token is shown once at onboarding.

create table if not exists public.beli_accounts (
  id uuid primary key default gen_random_uuid(),
  label text not null default 'beli',
  beli_id_enc text not null,
  password_enc text not null,
  token_hash text not null unique,
  token_prefix text not null,
  watcher_opt_in boolean not null default false,
  last_eats_scan timestamptz,
  created_at timestamptz not null default now()
);

alter table public.beli_accounts enable row level security;
revoke all on public.beli_accounts from public, anon, authenticated;
grant select, insert, update on public.beli_accounts to service_role;
