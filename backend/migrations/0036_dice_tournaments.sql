-- Dice: tournaments (date, hosts, enrolled players). Matchup scheduling is
-- handled outside this primitive for now (TBD in the product). All writes go
-- through the backend (service-role client), matching the dice_games
-- convention; RLS here only grants public read access.
--
-- Hosts are stored directly on the tournament row (not a join table) since a
-- tournament only ever has a handful of hosts and nothing queries "which
-- tournaments does user X host" today.

create table if not exists public.dice_tournaments (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  date date not null,
  host_user_ids uuid[] not null default '{}',
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists dice_tournaments_date_idx on public.dice_tournaments (date desc);

alter table public.dice_tournaments enable row level security;
create policy dice_tournaments_public_read on public.dice_tournaments
  for select to anon, authenticated
  using (true);

create table if not exists public.dice_tournament_enrollments (
  tournament_id uuid not null references public.dice_tournaments(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  enrolled_at timestamptz not null default now(),
  primary key (tournament_id, user_id)
);

create index if not exists dice_tournament_enrollments_tournament_id_idx
  on public.dice_tournament_enrollments (tournament_id);

alter table public.dice_tournament_enrollments enable row level security;
create policy dice_tournament_enrollments_public_read on public.dice_tournament_enrollments
  for select to anon, authenticated
  using (true);
