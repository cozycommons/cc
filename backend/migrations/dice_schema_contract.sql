-- Production Dice schema attestation. Keep this contract synchronized with
-- DICE_SCHEMA_CONTRACT_VERSION whenever a Dice migration is added.
do $$
declare
  object_name text;
  column_spec text;
begin
  foreach object_name in array array[
    'dice_profiles', 'dice_games', 'dice_game_players',
    'dice_tournaments', 'dice_tournament_enrollments', 'dice_feature_access',
    'dice_rating_mutation_receipts', 'dice_live_rating_repairs',
    'dice_live_matches', 'dice_live_referees', 'dice_live_commands', 'dice_live_events',
    'dice_virtual_markets', 'dice_virtual_picks', 'dice_virtual_ledger'
  ] loop
    if to_regclass('public.' || object_name) is null then
      raise exception 'Dice schema contract: missing table public.%', object_name;
    end if;
  end loop;

  foreach column_spec in array array[
    'dice_game_players.counts_for_group_stage',
    'dice_profiles.rating_deviation',
    'dice_profiles.elo_model_version',
    'dice_rating_mutation_receipts.mutation_id',
    'dice_rating_mutation_receipts.actor_id',
    'dice_rating_mutation_receipts.request_fingerprint',
    'dice_rating_mutation_receipts.source_digest',
    'dice_rating_mutation_receipts.output_digest',
    'dice_rating_mutation_receipts.players_updated',
    'dice_rating_mutation_receipts.profiles_updated',
    'dice_game_players.rating_deviation_before', 'dice_game_players.rating_deviation_after',
    'dice_games.source_live_match_id', 'dice_games.live_result_state', 'dice_games.duo_only',
    'dice_games.termination_reason', 'dice_games.detail_coverage', 'dice_games.stats_complete',
    'dice_games.recorded_stats',
    'dice_live_matches.rating_snapshot', 'dice_live_matches.prediction_snapshot',
    'dice_live_matches.ranked', 'dice_live_matches.deleted_at', 'dice_live_matches.deleted_by',
    'dice_live_rating_repairs.match_id', 'dice_live_rating_repairs.attempts',
    'dice_live_rating_repairs.last_error', 'dice_live_rating_repairs.updated_at',
    'dice_feature_access.enabled'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = split_part(column_spec, '.', 1)
        and column_name = split_part(column_spec, '.', 2)
    ) then
      raise exception 'Dice schema contract: missing column public.%', column_spec;
    end if;
  end loop;

  if exists (
       select 1 from information_schema.columns
       where table_schema = 'public'
         and table_name = 'dice_profiles'
         and column_name in ('rating_deviation', 'elo_model_version')
         and (
           is_nullable <> 'NO'
           or column_default is null
           or (column_name = 'rating_deviation' and column_default !~ '^350(::numeric)?$')
           or (column_name = 'elo_model_version' and column_default not like '%1.1.0%')
         )
     )
     or not exists (
       select 1 from pg_constraint
       where conrelid = 'public.dice_profiles'::regclass
         and conname = 'dice_profiles_rating_deviation_check'
         and convalidated
         and pg_get_constraintdef(oid) = 'CHECK (((rating_deviation >= (50)::numeric) AND (rating_deviation <= (350)::numeric)))'
     )
     or not exists (
       select 1 from pg_constraint
       where conrelid = 'public.dice_profiles'::regclass
         and conname = 'dice_profiles_canonical_model_version_check'
         and convalidated
         and pg_get_constraintdef(oid) = 'CHECK ((elo_model_version = ''1.1.0''::text))'
     )
     then
    raise exception 'Dice schema contract: canonical rating invariants are missing';
  end if;

  if exists (
       select 1 from public.dice_feature_access where enabled is false
     )
     or exists (
       select 1 from information_schema.columns
       where table_schema = 'public'
         and table_name = 'dice_feature_access'
         and column_name = 'enabled'
         and column_default is distinct from 'true'
     )
     or not exists (
       select 1 from pg_constraint
       where conrelid = 'public.dice_feature_access'::regclass
         and conname = 'dice_feature_access_released_check'
         and convalidated
         and pg_get_constraintdef(oid) = 'CHECK (enabled)'
     ) then
    raise exception 'Dice schema contract: retired live-referee opt-outs remain possible';
  end if;

  foreach object_name in array array[
    'public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text)',
    'public.dice_live_materialize_result(uuid,jsonb,text)',
    'public.dice_live_result_write_guard()',
    'public.dice_virtual_place_pick(uuid,bigint,uuid,text,text,integer)',
    'public.dice_virtual_open_bankroll(uuid,uuid,integer)',
    'public.dice_virtual_settle_market(bigint,text)',
    'public.dice_rating_source_snapshot()',
    'public.dice_rating_state_snapshot()',
    'public.dice_rating_mutation_receipt(uuid)',
    'public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb)',
    'public.dice_rating_commit(jsonb,jsonb,jsonb)',
    'public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)',
    'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)',
    'public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone)',
    'public.dice_rating_analytics_snapshot()',
    'public.dice_duo_replay_snapshot(integer)',
    'public.dice_live_prediction_snapshot_immutable()',
    'public.dice_live_set_ranked(uuid,boolean)',
    'public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)',
    'public.dice_live_sync_ranked_from_result()',
    'public.dice_live_track_rating_repair()',
    'public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean)',
    'public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid)'
  ] loop
    if to_regprocedure(object_name) is null then
      raise exception 'Dice schema contract: missing function %', object_name;
    end if;
  end loop;

  if to_regclass('public.dice_games_duo_replay_idx') is null
     or to_regclass('public.dice_game_players_duo_replay_idx') is null then
    raise exception 'Dice schema contract: duo replay indexes are missing';
  end if;

  if has_function_privilege('anon', 'public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)', 'execute')
     or has_function_privilege('authenticated', 'public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)', 'execute')
     or not has_function_privilege('service_role', 'public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)', 'execute') then
    raise exception 'Dice schema contract: canonical rebuild privileges are incorrect';
  end if;

  if pg_get_functiondef('public.dice_rating_source_snapshot()'::regprocedure)
       not like '%where g.duo_only is not true%'
     or pg_get_functiondef('public.dice_rating_state_snapshot()'::regprocedure)
       not like '%where g.duo_only is not true%'
     or pg_get_functiondef('public.dice_rating_analytics_snapshot()'::regprocedure)
       not like '%and g.duo_only is not true%' then
    raise exception 'Dice schema contract: individual snapshots include duo-only history';
  end if;

  if to_regclass('public.dice_elo_v11_refresh_status') is not null
     or to_regclass('public.dice_rating_control') is not null
     or to_regprocedure('public.dice_elo_v11_source_snapshot()') is not null
     or to_regprocedure('public.dice_elo_v11_state_snapshot()') is not null
     or to_regprocedure('public.dice_elo_v11_mark_dirty()') is not null
     or to_regprocedure('public.dice_elo_v11_promote(jsonb,jsonb,jsonb)') is not null
     or to_regprocedure('public.dice_rating_generation_snapshot()') is not null
     or to_regprocedure('public.dice_rating_commit_and_activate(jsonb,jsonb,jsonb,text,text)') is not null
     or to_regprocedure('public.dice_rating_control_snapshot()') is not null
     or to_regprocedure('public.dice_rating_mark_dirty()') is not null
     or to_regprocedure('public.dice_rating_status()') is not null
     or to_regprocedure('public.dice_rating_refresh_if_active(jsonb,jsonb,jsonb,text,text)') is not null
     or exists (
       select 1 from pg_trigger
       where tgname in (
         'dice_elo_v11_dirty_games',
         'dice_elo_v11_dirty_players',
         'dice_elo_v11_dirty_profiles',
         'dice_rating_dirty_games',
         'dice_rating_dirty_players',
         'dice_rating_dirty_profiles'
       ) and not tgisinternal
     )
     or pg_get_functiondef(
       'public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb)'::regprocedure
     ) like '%dice_elo_v11%'
     or exists (
       select 1 from information_schema.columns
       where table_schema = 'public'
         and (
           (table_name = 'dice_profiles' and column_name = 'elo_v11_rating')
           or (table_name = 'dice_game_players'
               and column_name in ('elo_v11_before', 'elo_v11_after'))
         )
     ) then
    raise exception 'Dice schema contract: retired rating control or shadow objects still exist';
  end if;

  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_games'::regclass
      and tgname = 'dice_game_reject_stale_update'
      and not tgisinternal
  ) then
    raise exception 'Dice schema contract: stale game update guard is missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_live_matches'::regclass
      and tgname = 'dice_live_prediction_snapshot_immutable'
      and not tgisinternal
  ) then
    raise exception 'Dice schema contract: prediction snapshot immutability trigger is missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_games'::regclass
      and tgname = 'dice_live_result_write_guard'
      and not tgisinternal
  ) then
    raise exception 'Dice schema contract: live-result write guard is missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_games'::regclass
      and tgname = 'dice_live_sync_ranked_from_result'
      and not tgisinternal
  ) then
    raise exception 'Dice schema contract: live-result ranked sync is missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_games'::regclass
      and tgname = 'dice_live_track_rating_repair'
      and not tgisinternal
  ) then
    raise exception 'Dice schema contract: live-result rating repair queue trigger is missing';
  end if;
  if pg_get_functiondef(
       'public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text)'::regprocedure
     ) not like '%dice:elo:canonical%' then
    raise exception 'Dice schema contract: live and manual rating writes are not serialized';
  end if;
  if has_function_privilege(
       'anon', 'public.dice_rating_source_snapshot()', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_source_snapshot()', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_rating_state_snapshot()', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_state_snapshot()', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_rating_mutation_receipt(uuid)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_mutation_receipt(uuid)', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb)', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_rating_commit(jsonb,jsonb,jsonb)', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_rating_commit(jsonb,jsonb,jsonb)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_commit(jsonb,jsonb,jsonb)', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone)', 'execute'
     ) or not has_function_privilege(
       'service_role', 'public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone)', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_game_reject_stale_update()', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_live_result_write_guard()', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_live_set_ranked(uuid,boolean)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_live_set_ranked(uuid,boolean)', 'execute'
     ) or not has_function_privilege(
       'service_role', 'public.dice_live_set_ranked(uuid,boolean)', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)', 'execute'
     ) or not has_function_privilege(
       'service_role', 'public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_live_sync_ranked_from_result()', 'execute'
     ) or has_function_privilege(
       'service_role', 'public.dice_live_track_rating_repair()', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean)', 'execute'
     ) or not has_function_privilege(
       'service_role', 'public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean)', 'execute'
     ) or has_function_privilege(
       'anon', 'public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid)', 'execute'
     ) or not has_function_privilege(
       'service_role', 'public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid)', 'execute'
  ) then
    raise exception 'Dice schema contract: rating RPCs are exposed outside service_role';
  end if;

  if not exists (
       select 1 from pg_proc
       where oid = 'public.dice_live_set_ranked(uuid,boolean)'::regprocedure
         and proconfig @> array['lock_timeout=2s']
     ) or not exists (
       select 1 from pg_proc
       where oid = 'public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)'::regprocedure
         and proconfig @> array['lock_timeout=2s']
     ) then
    raise exception 'Dice schema contract: live settings lock timeouts are missing';
  end if;

  if has_function_privilege(
       'anon', 'public.dice_duo_replay_snapshot(integer)', 'execute'
     ) or has_function_privilege(
       'authenticated', 'public.dice_duo_replay_snapshot(integer)', 'execute'
     ) then
    raise exception 'Dice schema contract: duo replay snapshot is server-only';
  end if;

  if has_table_privilege('service_role', 'public.dice_rating_mutation_receipts', 'insert')
     or has_table_privilege('service_role', 'public.dice_rating_mutation_receipts', 'update')
     or has_table_privilege('service_role', 'public.dice_rating_mutation_receipts', 'delete') then
    raise exception 'Dice schema contract: runtime can bypass canonical mutation receipts';
  end if;

  foreach object_name in array array[
    'dice_feature_access', 'dice_live_matches', 'dice_live_referees',
    'dice_live_commands', 'dice_live_events', 'dice_virtual_markets',
    'dice_virtual_picks', 'dice_virtual_ledger', 'dice_rating_mutation_receipts',
    'dice_live_rating_repairs'
  ] loop
    if not (select relrowsecurity from pg_class where oid = ('public.' || object_name)::regclass) then
      raise exception 'Dice schema contract: RLS disabled on public.%', object_name;
    end if;
    if has_table_privilege('anon', 'public.' || object_name, 'select')
       or has_table_privilege('authenticated', 'public.' || object_name, 'select') then
      raise exception 'Dice schema contract: private table public.% is browser-readable', object_name;
    end if;
  end loop;
end
$$;
