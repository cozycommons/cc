-- Dice: 2v2 team score/ELO tracker.
-- All writes go through the backend (service-role client) so it can enforce
-- creator/participant/admin edit permissions in Python; RLS here only grants
-- public read access (mirrors how other public-viewable stats are exposed).

create table if not exists public.dice_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  avatar_url text,
  elo_rating int not null default 1500,
  games_played int not null default 0,
  ranked_games_played int not null default 0,
  wins int not null default 0,
  losses int not null default 0,
  self_sinks int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists dice_profiles_elo_idx on public.dice_profiles (elo_rating desc);
create index if not exists dice_profiles_self_sinks_idx on public.dice_profiles (self_sinks desc);

alter table public.dice_profiles enable row level security;
create policy dice_profiles_public_read on public.dice_profiles
  for select to anon, authenticated
  using (true);

create table if not exists public.dice_games (
  id uuid primary key default gen_random_uuid(),
  created_by uuid not null references auth.users(id),
  ranked boolean not null default false,
  team1_score int not null,
  team2_score int not null,
  winner_team smallint not null,
  played_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint dice_games_winner_team_check check (winner_team in (1, 2)),
  constraint dice_games_scores_check check (team1_score >= 0 and team2_score >= 0)
);

create index if not exists dice_games_played_at_idx on public.dice_games (played_at desc);

alter table public.dice_games enable row level security;
create policy dice_games_public_read on public.dice_games
  for select to anon, authenticated
  using (true);

create table if not exists public.dice_game_players (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.dice_games(id) on delete cascade,
  user_id uuid not null references public.dice_profiles(user_id),
  team smallint not null,
  self_sinks int not null default 0,
  elo_before int,
  elo_after int,
  constraint dice_game_players_team_check check (team in (1, 2)),
  constraint dice_game_players_self_sinks_check check (self_sinks >= 0),
  unique (game_id, user_id)
);

create index if not exists dice_game_players_game_id_idx on public.dice_game_players (game_id);
create index if not exists dice_game_players_user_id_idx on public.dice_game_players (user_id);

alter table public.dice_game_players enable row level security;
create policy dice_game_players_public_read on public.dice_game_players
  for select to anon, authenticated
  using (true);
