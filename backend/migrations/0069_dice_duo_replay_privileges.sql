-- Hosted Supabase can grant new public-schema functions directly to API roles.
-- Revoke both the PUBLIC inheritance path and those explicit role grants.
revoke all on function public.dice_duo_replay_snapshot(integer) from public;
revoke all on function public.dice_duo_replay_snapshot(integer) from anon;
revoke all on function public.dice_duo_replay_snapshot(integer) from authenticated;
grant execute on function public.dice_duo_replay_snapshot(integer) to service_role;
