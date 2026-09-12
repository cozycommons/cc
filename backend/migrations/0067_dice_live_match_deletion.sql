-- User-facing deletion for live matches. The event ledger remains immutable;
-- this tombstones the match and removes only its derived dice_games row.

alter table public.dice_live_matches
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by uuid references public.dice_profiles(user_id);

create index if not exists dice_live_matches_visible_idx
  on public.dice_live_matches (updated_at desc)
  where deleted_at is null;
