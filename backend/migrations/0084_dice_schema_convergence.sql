-- Converge the imported Dice schema before retiring the numeric baseline.
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
ALTER TABLE public.dice_schema_migrations
 ADD COLUMN reconciled_by integer,
 ADD COLUMN reconciliation_reason text,
 ADD CONSTRAINT dice_schema_migrations_reconciliation_source
 FOREIGN KEY (reconciled_by) REFERENCES public.dice_schema_migrations(version)
 DEFERRABLE INITIALLY DEFERRED,
 ADD CONSTRAINT dice_schema_migrations_reconciliation_provenance CHECK (
  (recorded_via='reconciled' AND reconciled_by IS NOT NULL AND reconciled_by=84 AND checksum IS NOT NULL
   AND version IN (20,25,31,32,33,34,35,36,37,38,39,40,41,42)
   AND reconciliation_reason IS NOT NULL AND length(reconciliation_reason)>0)
  OR (recorded_via IN ('legacy','executed') AND reconciled_by IS NULL AND reconciliation_reason IS NULL)
 );
DO $$ BEGIN
 IF EXISTS(SELECT FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_duration_ms_check')
 AND NOT EXISTS(SELECT FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_duration_check') THEN
  ALTER TABLE public.dice_live_command_metrics RENAME CONSTRAINT dice_live_command_metrics_duration_ms_check TO dice_live_command_metrics_duration_check;
 END IF;
 IF EXISTS(SELECT FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_hedge_delay_ms_check')
 AND NOT EXISTS(SELECT FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_hedge_delay_check') THEN
  ALTER TABLE public.dice_live_command_metrics RENAME CONSTRAINT dice_live_command_metrics_hedge_delay_ms_check TO dice_live_command_metrics_hedge_delay_check;
 END IF;
END $$;
ALTER TABLE public.dice_live_command_metrics DROP CONSTRAINT dice_live_command_metrics_referee_id_fkey;
ALTER TABLE public.dice_live_command_metrics ADD CONSTRAINT dice_live_command_metrics_referee_id_fkey
 FOREIGN KEY (referee_id) REFERENCES public.dice_profiles(user_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS dice_live_command_metrics_match_idx ON public.dice_live_command_metrics(match_id,created_at DESC);

REVOKE ALL ON TABLE public.dice_profiles,public.dice_games,public.dice_game_players,
 public.dice_game_comments,public.dice_tournaments,public.dice_tournament_enrollments FROM PUBLIC,anon,authenticated;
GRANT SELECT ON TABLE public.dice_profiles,public.dice_games,public.dice_game_players,
 public.dice_game_comments,public.dice_tournaments,public.dice_tournament_enrollments TO anon,authenticated;
DO $$ DECLARE sequence_name text; BEGIN
 FOREACH sequence_name IN ARRAY ARRAY['analytics_events_id_seq','commons_scene_commands_id_seq',
 'dice_live_command_metrics_id_seq','dice_virtual_ledger_id_seq','dice_virtual_markets_id_seq','dice_virtual_picks_id_seq'] LOOP
  IF to_regclass('public.'||sequence_name) IS NOT NULL THEN
   EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM PUBLIC,anon,authenticated',sequence_name);
  END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO anon,authenticated,service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC,anon,authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC,anon,authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION public.dice_release_readiness()
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $readiness$
BEGIN
 IF NOT EXISTS(SELECT FROM public.dice_schema_migrations WHERE version=84) OR NOT EXISTS(SELECT FROM public.commons_schema_migrations WHERE version=12) THEN
 RAISE EXCEPTION 'release schema receipt missing'; END IF;
 EXECUTE $dice_contract$-- Production Dice schema attestation. Keep this contract synchronized with
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

DO $$ BEGIN
 IF to_regclass('public.analytics_saved_queries') IS NULL
 OR NOT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='analytics' AND c.relname='events' AND c.relkind='v')
 OR NOT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='analytics' AND c.relname='users' AND c.relkind='v')
 OR NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='analytics_events' AND column_name='identity_status') THEN
  RAISE EXCEPTION 'Analytics workspace schema missing';
 END IF;
END $$;

DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM public.dice_schema_migrations WHERE version=84)
 OR EXISTS(SELECT 1 FROM (VALUES (20),(25),(31),(32),(33),(34),(35),(36),(37),(38),(39),(40),(41),(42)) expected(version)
 WHERE NOT EXISTS(SELECT FROM public.dice_schema_migrations applied WHERE applied.version=expected.version)) THEN
  RAISE EXCEPTION 'Dice migration history reconciliation missing';
 END IF;
END $$;
$dice_contract$;
 EXECUTE $commons_contract$-- Commons schema attestation. This is intentionally separate from Dice's
-- project schema contract because Commons owns the home scene.
do $$
declare
  object_name text;
begin
  foreach object_name in array array[
    'commons_scenes',
    'commons_scene_commands'
  ] loop
    if to_regclass('public.' || object_name) is null then
      raise exception 'Commons schema contract: missing table public.%', object_name;
    end if;
  end loop;

  if to_regprocedure('public.commons_apply_command(text,text,text,integer,jsonb,jsonb)') is null then
    raise exception 'Commons schema contract: missing command function';
  end if;

  foreach object_name in array array[
    'commons_scenes',
    'commons_scene_commands'
  ] loop
    if not (
      select relrowsecurity
        from pg_class
       where oid = ('public.' || object_name)::regclass
    ) then
      raise exception 'Commons schema contract: RLS disabled on public.%', object_name;
    end if;
  end loop;
end;
$$;
$commons_contract$;
 RETURN true;
END $readiness$;
REVOKE ALL ON FUNCTION public.dice_release_readiness() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.dice_release_readiness() TO service_role;

-- Accept imported history only after its complete final schema is verified.
DO $verify$ DECLARE fingerprint text; BEGIN
 SELECT md5(string_agg(kind||chr(31)||key||chr(31)||definition::text,chr(30)
 ORDER BY kind COLLATE "C",key COLLATE "C")) INTO fingerprint
 FROM pg_temp.cozy_schema_catalog_v1()
 WHERE key LIKE 'public.dice_%' OR key LIKE 'public.analytics_%' OR key LIKE 'analytics.%'
 OR kind IN ('schema_acl','default_acl');
 IF fingerprint IS DISTINCT FROM '65fa7198f86994e7034640df43da88e0' THEN
  RAISE EXCEPTION 'Dice schema convergence mismatch: expected 65fa7198f86994e7034640df43da88e0, got %; inspect catalog differences before reconciling history',fingerprint;
 END IF;
END $verify$;
INSERT INTO public.dice_schema_migrations(version,checksum,recorded_via,reconciled_by,reconciliation_reason)
SELECT expected.version,expected.checksum,'reconciled',84,
 'Imported schema verified against the canonical fresh Dice 0084 schema; historical SQL was not replayed.'
FROM (VALUES
 (20,'af5fbae55f90ccb6b1b62eba2d73021e1fa40012f5af3da4afc4fcafc00212a0'),
 (25,'96250fda2fcde80eefdbf1f032425dd2686ad29602c6e7977b6d6dea463ede7c'),
 (31,'ba976d6c576eea3a1bab484ba2298def779c52e1678f3528ef97ca62774617a1'),
 (32,'6d5fe765feadaccd22f9b9ea314886dcbe5fffc87152d90b8cf36d835a5ef816'),
 (33,'b014d0a2eb44dfd3d427cf959caa71507a8204ad4c5fb4c99ae94a27d3c88f32'),
 (34,'360964e652d58f852aea1458662c6f0ff6f25344637179b3630857361de6a7e7'),
 (35,'e87f0cf9edad9e5a2c34323c7209c9a0a1c3955c928404541c14a28dc47aa8d9'),
 (36,'52c752715f8af03338248d6b312d8cc976ace0755d622c8d72b1469d85c2ee67'),
 (37,'17121494ffe152af59b06178a6e5704586a7ff64a98bcf7ec32f653964bfb0c5'),
 (38,'0e62e7991ecd1a974cbbc5d3e226a7978925ac8d7b33cf23bdb14629a5887f91'),
 (39,'d710d3ec6c47e2cb95ba09af09aa1cf02a5f3309085bc64fa1e59eab36e884b4'),
 (40,'ea2d22f86d44947105f09b44105b9c81d486be4c2c4fe91ef141c957636d7fde'),
 (41,'d1dddb1da1bdbe8ca9760ca4a0eab267e4d212dbd9e7093d3ebb571c8d2b7d83'),
 (42,'929b81d68ff6f04f729ad2ccd0baff2327028f7740d282ac8ea69c0ecb7ba069')
) expected(version,checksum)
WHERE NOT EXISTS(SELECT FROM public.dice_schema_migrations applied WHERE applied.version=expected.version);
