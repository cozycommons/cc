-- ESPN Fantasy app: league snapshot history.
-- One row per captured league snapshot: the full payload built at capture
-- time, kept as append-only history for trend computation (ownership
-- movement, player performance, team form). Capture-on-read in v1.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.espn_snapshots (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.espn_accounts(id) on delete cascade,
  league_id bigint not null,
  season integer not null,
  payload jsonb not null,
  captured_at timestamptz not null default now()
);

create index if not exists espn_snapshots_account_captured_idx
  on public.espn_snapshots (account_id, captured_at desc);

alter table public.espn_snapshots enable row level security;
revoke all on public.espn_snapshots from public, anon, authenticated;
grant select, insert on public.espn_snapshots to service_role;
