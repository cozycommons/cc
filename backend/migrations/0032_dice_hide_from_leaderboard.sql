-- Lets a Dice player opt their profile out of the ELO and self-sink
-- leaderboards while still keeping their stats/history visible on their
-- own profile page and in match rows elsewhere.

alter table public.dice_profiles
  add column if not exists hide_from_leaderboard boolean not null default false;
