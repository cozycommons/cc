-- Capture the server-owned Elo inputs when a live match is created.
-- Existing matches remain valid and intentionally fall back to a neutral prior.
alter table public.dice_live_matches
  add column if not exists rating_snapshot jsonb;

comment on column public.dice_live_matches.rating_snapshot is
  'Immutable-at-creation Elo inputs for optional live prediction; null means neutral prior.';
