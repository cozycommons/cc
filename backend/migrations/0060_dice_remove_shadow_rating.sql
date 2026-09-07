-- Remove the retired shadow Elo storage and operator surface. Canonical Elo,
-- rating deviation, and their historical snapshots remain authoritative.

do $$
declare
  old_definition text;
  new_definition text;
begin
  select pg_get_functiondef(
    'public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb)'::regprocedure
  ) into old_definition;
  new_definition := replace(
    old_definition,
    E'public.dice_profiles,\n    public.dice_elo_v11_refresh_status',
    'public.dice_profiles'
  );
  if new_definition like '%dice_elo_v11%' then
    raise exception 'Dice cleanup: canonical mutation still depends on shadow state';
  end if;
  if new_definition <> old_definition then
    execute new_definition;
  end if;
end
$$;

drop trigger if exists dice_elo_v11_dirty_games on public.dice_games;
drop trigger if exists dice_elo_v11_dirty_players on public.dice_game_players;
drop trigger if exists dice_elo_v11_dirty_profiles on public.dice_profiles;

drop function if exists public.dice_elo_v11_promote(jsonb, jsonb, jsonb);
drop function if exists public.dice_elo_v11_state_snapshot();
drop function if exists public.dice_elo_v11_source_snapshot();
drop function if exists public.dice_elo_v11_mark_dirty();
drop table if exists public.dice_elo_v11_refresh_status;

alter table public.dice_profiles drop column if exists elo_v11_rating;
alter table public.dice_game_players
  drop column if exists elo_v11_before,
  drop column if exists elo_v11_after;
