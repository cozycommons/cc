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
