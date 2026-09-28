-- Resy app: per-user account storage.
-- One row per friend: encrypted Resy email + password + cached auth token,
-- plus the hashed personal API token. Plaintext tokens and passwords are
-- never stored; the token is shown once at onboarding.
-- Cards stay on Resy's side; only the account-scoped numeric
-- payment_method_id is ever referenced at booking time.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.resy_accounts (
  id uuid primary key default gen_random_uuid(),
  label text not null default 'resy',
  email_enc text not null,
  password_enc text not null,
  auth_token_enc text not null default '',
  token_hash text not null unique,
  token_prefix text not null,
  created_at timestamptz not null default now()
);

alter table public.resy_accounts enable row level security;
revoke all on public.resy_accounts from public, anon, authenticated;
grant select, insert, update on public.resy_accounts to service_role;
