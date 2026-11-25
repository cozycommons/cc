-- Maple telemetry: per-user accounts and EXP overlay log rows.
-- One row per person: a hashed personal API token ("ccm_..."); the
-- plaintext is shown once at onboarding and never stored. There are no
-- third-party credentials in this module, so nothing is encrypted here.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.maple_accounts (
  id uuid primary key default gen_random_uuid(),
  label text not null default 'maple',
  token_hash text not null unique,
  token_prefix text not null,
  owner_user_id uuid,
  created_at timestamptz not null default now()
);

alter table public.maple_accounts enable row level security;
revoke all on public.maple_accounts from public, anon, authenticated;
grant select, insert, update, delete on public.maple_accounts to service_role;

-- One row per EXP overlay log line (exp_log.json `entries`): the totals
-- for one day, map, level, class and party size. run_id is a sha256 over
-- the line's key (producer, source install, date, map, level, party,
-- class), computed identically by the shipper and the backend, so a
-- re-post upserts the same row with newer totals instead of duplicating
-- it. Phase 2 producers (FM watcher) get their own tables keyed the
-- same way; user_id is the maple_accounts id on every telemetry row.
create table if not exists public.maple_exp_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.maple_accounts(id) on delete cascade,
  run_id text not null,
  producer text not null default 'exp',
  log_date date not null,
  map text not null,
  map_read text,
  level integer,
  class text,
  party integer,
  exp bigint not null,
  seconds double precision not null,
  mesos bigint not null default 0,
  mesos_seconds double precision not null default 0,
  potion_cost bigint,
  potion_seconds double precision,
  estimated boolean not null default false,
  source_install text,
  source_updated double precision,
  received_at timestamptz not null default now(),
  unique (user_id, run_id)
);

create index if not exists maple_exp_runs_user_date_idx
  on public.maple_exp_runs (user_id, log_date desc);

alter table public.maple_exp_runs enable row level security;
revoke all on public.maple_exp_runs from public, anon, authenticated;
grant select, insert, update, delete on public.maple_exp_runs to service_role;
