-- Links a logged match back to the tournament it was played as part of (if
-- any). Nullable: most games aren't tied to a tournament. Once a scheduled
-- tournament match's result is entered, it becomes a normal dice_games row
-- tagged with this column -- so it shows up both on the tournament page
-- (completed matches + standings) and in the regular match history/home
-- feed, with no separate code path needed for the latter.

alter table public.dice_games
  add column if not exists tournament_id uuid references public.dice_tournaments(id) on delete set null;

create index if not exists dice_games_tournament_id_idx on public.dice_games (tournament_id);
