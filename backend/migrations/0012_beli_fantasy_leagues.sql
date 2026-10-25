-- Season settings are read and written only by the backend service role.
create table public.fantasy_leagues (
  season int primary key check (season between 2000 and 2100),
  espn_league_id text not null check (espn_league_id ~ '^[0-9]{1,12}$'),
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id) on delete set null
);
alter table public.fantasy_leagues enable row level security;
revoke all on public.fantasy_leagues from public, anon, authenticated, service_role;
grant select, insert, update on public.fantasy_leagues to service_role;
