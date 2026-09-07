-- Tracks "sinks" (successful shots) per player per game, alongside the
-- existing self_sinks (own-cup misses), plus the aggregate on the profile.

alter table public.dice_game_players
  add column if not exists sinks int not null default 0;

alter table public.dice_game_players
  drop constraint if exists dice_game_players_sinks_check,
  add constraint dice_game_players_sinks_check check (sinks >= 0);

alter table public.dice_profiles
  add column if not exists sinks int not null default 0;

create index if not exists dice_profiles_sinks_idx on public.dice_profiles (sinks desc);
