-- ESPN Fantasy app: per-user account storage.
-- One row per friend: encrypted ESPN cookies (espn_s2 + SWID) for a single
-- league, plus the hashed personal API token. Plaintext tokens and cookies
-- are never stored; the token is shown once at onboarding.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.espn_accounts (
  id uuid primary key default gen_random_uuid(),
  label text not null default 'espn',
  league_id bigint not null,
  season integer not null,
  espn_s2_enc text not null,
  swid_enc text not null,
  token_hash text not null unique,
  token_prefix text not null,
  created_at timestamptz not null default now()
);

alter table public.espn_accounts enable row level security;
revoke all on public.espn_accounts from public, anon, authenticated;
grant select, insert, update on public.espn_accounts to service_role;
