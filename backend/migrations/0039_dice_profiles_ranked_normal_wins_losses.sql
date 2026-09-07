-- Splits each player's aggregate wins/losses into ranked vs normal (casual)
-- buckets so the profile page can show both breakdowns separately, instead
-- of only the combined record. wins/losses are kept as-is (still the
-- combined totals used by the leaderboard/players list).

alter table public.dice_profiles
  add column if not exists ranked_wins int not null default 0,
  add column if not exists ranked_losses int not null default 0,
  add column if not exists normal_wins int not null default 0,
  add column if not exists normal_losses int not null default 0;
