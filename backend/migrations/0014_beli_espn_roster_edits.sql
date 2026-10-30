-- ESPN Fantasy: approval-gated roster edits (add / drop).
-- A roster edit is proposed first: the backend validates it against the
-- live league (add target is a free agent, drop target is rostered by
-- the account's own team, the post-edit roster is legal) and persists
-- the validated snapshot here with status 'pending' and a short expiry.
-- A separate approve call then executes the edit as ONE ESPN
-- transaction and records the outcome back on the row (executed /
-- waiver_pending / failed). This table is the audit trail for every
-- roster write, the same role espn_lineup_runs plays for lineup writes
-- (migration 0008) — except that an edit row mutates through its
-- lifecycle, so service_role needs update as well as select/insert.
-- Lives in the shared app-schema ("beli") family; see migration_runner.py.

create table if not exists public.espn_roster_edits (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.espn_accounts(id) on delete cascade,
  league_id bigint not null,
  season integer not null,
  team_id integer not null,
  add_player_id integer,
  drop_player_id integer,
  add_player jsonb,
  drop_player jsonb,
  preview text not null,
  status text not null default 'pending',
  error text,
  espn_transaction jsonb,
  expires_at timestamptz not null,
  executed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists espn_roster_edits_account_created_idx
  on public.espn_roster_edits (account_id, created_at desc);

alter table public.espn_roster_edits enable row level security;
revoke all on public.espn_roster_edits from public, anon, authenticated;
grant select, insert, update on public.espn_roster_edits to service_role;
