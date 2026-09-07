-- Dice tournaments: switch the date-only `date` column to a `starts_at`
-- timestamptz so a tournament can specify a date *and* time (the app
-- assumes/renders this in America/New_York — Dice's default timezone —
-- without ever surfacing the zone in the UI). Also adds a generic `data`
-- jsonb column so new tournament fields (starting with `description`) can
-- be added going forward without further table changes.

alter table public.dice_tournaments
  rename column date to starts_at;

alter table public.dice_tournaments
  alter column starts_at type timestamptz using starts_at::timestamptz;

alter table public.dice_tournaments
  add column if not exists data jsonb not null default '{}'::jsonb;

drop index if exists public.dice_tournaments_date_idx;
create index if not exists dice_tournaments_starts_at_idx on public.dice_tournaments (starts_at desc);
