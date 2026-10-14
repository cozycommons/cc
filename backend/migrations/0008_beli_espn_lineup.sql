-- ESPN Fantasy app v2: automatic daily lineup setting.
-- Adds the per-account automation opt-in flag and the append-only lineup
-- run log. Every automation run (live or dry-run) records its plan, the
-- moves submitted, any conflicts (a scheduled player forced to sit, an
-- auth failure, a verify mismatch), and errors here, so conflicts can be
-- pulled on demand via GET /espn/lineup/runs.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

alter table public.espn_accounts
  add column if not exists lineup_automation_enabled boolean not null default false;

create table if not exists public.espn_lineup_runs (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.espn_accounts(id) on delete cascade,
  league_id bigint not null,
  season integer not null,
  scoring_period_id integer,
  mode text not null default 'live',
  status text not null,
  plan jsonb,
  moves jsonb not null default '[]'::jsonb,
  conflicts jsonb not null default '[]'::jsonb,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists espn_lineup_runs_account_created_idx
  on public.espn_lineup_runs (account_id, created_at desc);

alter table public.espn_lineup_runs enable row level security;
revoke all on public.espn_lineup_runs from public, anon, authenticated;
grant select, insert on public.espn_lineup_runs to service_role;
