-- Replace "hide from leaderboard" with anonymous play. Hiding dropped every
-- game involving a hidden player from duo ratings and ranks, which corrupted
-- other players' records. Anonymous players count everywhere and are shown as
-- a reshuffled "Anonymous <Animal>" on recorded results by the API.
--
-- Players who had hidden themselves keep their privacy as anonymous players;
-- the old flag is cleared for everyone and no longer read or written.

alter table public.dice_profiles
  add column if not exists is_anonymous boolean not null default false;

update public.dice_profiles
   set is_anonymous = true,
       hide_from_leaderboard = false
 where hide_from_leaderboard;

-- Every read of these tables goes through the API, which applies anonymity.
-- Browser roles reading them directly (with the public anon key) would see
-- anonymous players' real ids on every recorded result, so they lose SELECT.
-- Comments stay readable; their authors are shown by name everywhere.
revoke select on table
  public.dice_profiles,
  public.dice_games,
  public.dice_game_players,
  public.dice_tournaments,
  public.dice_tournament_enrollments
  from anon, authenticated;
