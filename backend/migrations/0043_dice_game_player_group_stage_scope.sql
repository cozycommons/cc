-- A substitute may receive ELO from a ranked game without receiving a
-- group-stage win/loss or affecting tournament seeding.
alter table public.dice_game_players
  add column if not exists counts_for_group_stage boolean not null default true;
