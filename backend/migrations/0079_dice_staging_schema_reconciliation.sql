CREATE INDEX IF NOT EXISTS dice_live_matches_visible_idx ON public.dice_live_matches USING btree (updated_at DESC) WHERE (deleted_at IS NULL);
CREATE INDEX IF NOT EXISTS dice_games_duo_replay_idx ON public.dice_games USING btree (played_at, created_at, id);
CREATE INDEX IF NOT EXISTS dice_game_players_duo_replay_idx ON public.dice_game_players USING btree (game_id, team, user_id);
CREATE INDEX IF NOT EXISTS dice_live_command_metrics_created_at_idx ON public.dice_live_command_metrics USING btree (created_at DESC);

-- Reconcile a staged Dice database whose version ledger was copied without
-- the matching functions, triggers, policies and constraints. No event/history
-- rows are replaced. Definitions attested against the source release 0078.


CREATE OR REPLACE FUNCTION public.dice_duo_replay_snapshot(p_max_games integer DEFAULT 5000)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
  select case
    when p_max_games < 1 then jsonb_build_object('snapshot_version', 'dice-rating-analytics/v1', 'error', 'invalid_limit')
    when (select count(*) from public.dice_games g where g.live_result_state is null or g.live_result_state = 'official') > p_max_games
      then jsonb_build_object('snapshot_version', 'dice-rating-analytics/v1', 'error', 'history_limit_exceeded')
    else jsonb_build_object(
      'snapshot_version', 'dice-rating-analytics/v1',
      'profiles', coalesce((
        select jsonb_agg(jsonb_build_object(
          'user_id', p.user_id, 'display_name', p.display_name,
          'avatar_url', p.avatar_url,
          'elo_rating', p.elo_rating, 'rating_deviation', p.rating_deviation,
          'elo_model_version', p.elo_model_version,
          'ranked_games_played', p.ranked_games_played,
          'games_played', p.games_played, 'wins', p.wins, 'losses', p.losses,
          'ranked_wins', p.ranked_wins, 'ranked_losses', p.ranked_losses,
          'normal_wins', p.normal_wins, 'normal_losses', p.normal_losses,
          'self_sinks', p.self_sinks, 'sinks', p.sinks,
          'hide_from_leaderboard', p.hide_from_leaderboard
        ) order by p.user_id)
        from public.dice_profiles p
      ), '[]'::jsonb),
      'games', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', g.id, 'ranked', g.ranked, 'duo_only', g.duo_only,
          'winner_team', g.winner_team, 'team1_score', g.team1_score,
          'team2_score', g.team2_score, 'played_at', g.played_at,
          'created_at', g.created_at, 'live_result_state', g.live_result_state
        ) order by g.played_at, g.created_at, g.id)
        from public.dice_games g
        where g.live_result_state is null or g.live_result_state = 'official'
      ), '[]'::jsonb),
      'players', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', gp.id, 'game_id', gp.game_id, 'user_id', gp.user_id,
          'team', gp.team, 'self_sinks', gp.self_sinks, 'sinks', gp.sinks,
          'elo_before', gp.elo_before, 'elo_after', gp.elo_after,
          'rating_deviation_before', gp.rating_deviation_before,
          'rating_deviation_after', gp.rating_deviation_after
        ) order by gp.game_id, gp.user_id, gp.id)
        from public.dice_game_players gp
        join public.dice_games g on g.id = gp.game_id
        where g.live_result_state is null or g.live_result_state = 'official'
      ), '[]'::jsonb)
    )
  end
$function$
;

REVOKE ALL ON FUNCTION public.dice_duo_replay_snapshot(integer) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_duo_replay_snapshot(integer) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_game_reject_stale_update()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  expected_updated_at text;
begin
  expected_updated_at := current_setting('dice.game_expected_updated_at', true);
  if coalesce(expected_updated_at, '') <> ''
     and old.updated_at is distinct from expected_updated_at::timestamptz then
    raise exception using errcode = 'P0001', message = 'dice_game.stale_update';
  end if;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_game_reject_stale_update() FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.dice_live_append_command_v1(p_match_id uuid, p_recorded_by uuid, p_client_command_id text, p_expected_version integer, p_canonical_payload jsonb, p_events jsonb, p_projection jsonb, p_score smallint[], p_status text, p_detail_coverage text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_match public.dice_live_matches%rowtype;
  v_command public.dice_live_commands%rowtype;
  v_new_version integer;
  v_first_sequence integer;
  v_event jsonb;
  v_sequence integer;
  v_command_index integer;
  v_receipt jsonb;
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  if jsonb_typeof(p_events) <> 'array' or jsonb_array_length(p_events) not between 1 and 2 then
    raise exception using errcode = '22023', message = 'dice_live.invalid_command';
  end if;
  if cardinality(p_score) <> 2 or p_status not in ('active', 'awaiting_replay', 'ready_to_finish', 'completed')
     or p_detail_coverage not in ('complete', 'partial', 'unknown') then
    raise exception using errcode = '22023', message = 'dice_live.invalid_projection';
  end if;

  -- The identity check deliberately precedes the version check.  An exact
  -- timeout retry remains idempotent even after another command advanced N.
  select * into v_command
    from public.dice_live_commands
   where match_id = p_match_id
     and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  if found then
    if v_command.canonical_payload = p_canonical_payload then
      return v_command.receipt;
    end if;
    raise exception using
      errcode = 'P0001', message = 'dice_live.command_id_conflict',
      detail = jsonb_build_object('match_id', p_match_id, 'client_command_id', p_client_command_id)::text;
  end if;

  select * into v_match from public.dice_live_matches where id = p_match_id for update;
  if not found then
    raise exception using errcode = 'P0001', message = 'dice_live.match_not_found';
  end if;
  if not exists (
    select 1 from public.dice_live_referees
     where match_id = p_match_id and user_id = p_recorded_by and left_at is null
  ) then
    raise exception using errcode = '42501', message = 'dice_live.referee_not_joined';
  end if;
  if v_match.version <> p_expected_version then
    raise exception using
      errcode = 'P0001', message = 'dice_live.stale_version',
      detail = jsonb_build_object(
        'current_version', v_match.version,
        'projection', v_match.projection
      )::text;
  end if;

  v_new_version := v_match.version + 1;
  select coalesce(max(sequence), 0) + 1 into v_first_sequence
    from public.dice_live_events where match_id = p_match_id;
  for v_event, v_command_index in
    select value, ordinality::integer - 1
      from jsonb_array_elements(p_events) with ordinality
  loop
    v_sequence := v_first_sequence + v_command_index;
    v_event := jsonb_set(v_event, '{match_id}', to_jsonb(p_match_id::text), true);
    v_event := jsonb_set(v_event, '{match_version}', to_jsonb(v_new_version), true);
    v_event := jsonb_set(v_event, '{sequence}', to_jsonb(v_sequence), true);
    v_event := jsonb_set(v_event, '{client_command_id}', to_jsonb(p_client_command_id), true);
    v_event := jsonb_set(v_event, '{command_index}', to_jsonb(v_command_index), true);
    v_event := jsonb_set(v_event, '{recorded_by}', to_jsonb(p_recorded_by::text), true);
    v_event := jsonb_set(v_event, '{recorded_at}', to_jsonb(now()), true);
    insert into public.dice_live_events (
      id, match_id, match_version, sequence, client_command_id, command_index,
      recorded_by, recorded_at, match_elapsed_ms, kind, event
    ) values (
      v_event->>'id', p_match_id, v_new_version, v_sequence,
      p_client_command_id, v_command_index, p_recorded_by,
      coalesce((v_event->>'recorded_at')::timestamptz, now()),
      coalesce((v_event->>'match_elapsed_ms')::integer, 0),
      v_event->>'kind', v_event
    );
  end loop;

  v_receipt := jsonb_build_object(
    'accepted_version', v_new_version,
    'first_sequence', v_first_sequence,
    'last_sequence', v_first_sequence + jsonb_array_length(p_events) - 1,
    'projection', p_projection,
    'official_result', null
  );
  insert into public.dice_live_commands (
    match_id, recorded_by, client_command_id, canonical_payload,
    expected_version, accepted_version, first_sequence, last_sequence, receipt
  ) values (
    p_match_id, p_recorded_by, p_client_command_id, p_canonical_payload,
    p_expected_version, v_new_version, v_first_sequence,
    v_first_sequence + jsonb_array_length(p_events) - 1, v_receipt
  );
  update public.dice_live_matches
     set version = v_new_version,
         status = p_status,
         score = p_score,
         detail_coverage = p_detail_coverage,
         projection = p_projection,
         updated_at = now()
   where id = p_match_id;
  return v_receipt;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_append_command_v1(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_append_command_v1(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_append_command(p_match_id uuid, p_recorded_by uuid, p_client_command_id text, p_expected_version integer, p_canonical_payload jsonb, p_events jsonb, p_projection jsonb, p_score smallint[], p_status text, p_detail_coverage text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_receipt jsonb;
  official jsonb;
  already_exists boolean;
begin
  if coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
    ''
  ) <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:canonical', 0)
  );
  if not exists (
    select 1 from public.dice_live_matches
    where id = p_match_id and deleted_at is null
  ) then
    raise exception using errcode = 'P0001', message = 'dice_live.match_not_found';
  end if;
  perform set_config('request.jwt.claim.role', 'service_role', true);
  select true into already_exists from public.dice_live_commands
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  v_receipt := public.dice_live_append_command_v1(
    p_match_id, p_recorded_by, p_client_command_id, p_expected_version,
    p_canonical_payload, p_events, p_projection, p_score, p_status, p_detail_coverage);
  if already_exists then return v_receipt; end if;
  perform set_config('dice.live_materialization', 'on', true);
  official := public.dice_live_materialize_result(p_match_id, p_projection, p_status);
  v_receipt := jsonb_set(
    v_receipt, '{official_result}', coalesce(official, 'null'::jsonb), true
  );
  update public.dice_live_commands set receipt = v_receipt
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  return v_receipt;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text) TO service_role;

COMMENT ON FUNCTION public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text) IS 'Atomic live command materialization. Live results are unranked; ranked live support must use the canonical rating mutation transaction.';

CREATE OR REPLACE FUNCTION public.dice_live_apply_ranked_rating_mutation(p_mutation_id uuid, p_source jsonb, p_operation text, p_game jsonb, p_players jsonb, p_expected_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb, p_source_digest text, p_output_digest text, p_actor_id text, p_request_fingerprint text)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '2s'
AS $function$
  select public.dice_rating_apply_game_mutation(
    p_mutation_id, p_source, p_operation, p_game, p_players,
    p_expected_source, p_player_snapshots, p_profile_states,
    p_source_digest, p_output_digest, p_actor_id, p_request_fingerprint
  );
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_apply_ranked_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_create_match(p_match_id uuid, p_created_by uuid, p_team_order jsonb, p_teams jsonb, p_rules_snapshot jsonb, p_rating_snapshot jsonb, p_prediction_snapshot jsonb, p_ranked boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  created public.dice_live_matches%rowtype;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:live:create:' || p_match_id::text, 0)
  );
  select * into created from public.dice_live_matches where id = p_match_id;
  if found then
    if created.deleted_at is not null
       or created.created_by is distinct from p_created_by
       or created.team_order is distinct from p_team_order
       or created.teams is distinct from p_teams
       or created.rules_snapshot is distinct from p_rules_snapshot
       or created.ranked is distinct from p_ranked
       or not exists (
         select 1 from public.dice_live_referees
         where match_id = p_match_id and user_id = p_created_by and left_at is null
       ) then
      raise exception using errcode = '23505', message = 'dice_live.create_idempotency_conflict';
    end if;
    return to_jsonb(created);
  end if;
  insert into public.dice_live_matches (
    id, created_by, team_order, teams, rules_snapshot, rating_snapshot,
    prediction_snapshot, ranked
  ) values (
    p_match_id, p_created_by, p_team_order, p_teams, p_rules_snapshot, p_rating_snapshot,
    p_prediction_snapshot, p_ranked
  ) returning * into created;
  insert into public.dice_live_referees (match_id, user_id)
  values (created.id, p_created_by);
  return to_jsonb(created);
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_create_match(uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb,boolean) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_delete_with_rating_mutation(p_mutation_id uuid, p_source jsonb, p_operation text, p_game jsonb, p_players jsonb, p_expected_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb, p_source_digest text, p_output_digest text, p_actor_id text, p_request_fingerprint text, p_match_id uuid, p_deleted_by uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  committed jsonb;
  affected integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  if p_operation <> 'delete' or p_game->>'id' is null then
    raise exception using errcode = '22023', message = 'dice_live.invalid_delete_mutation';
  end if;
  committed := public.dice_rating_apply_game_mutation(
    p_mutation_id, p_source, p_operation, p_game, p_players,
    p_expected_source, p_player_snapshots, p_profile_states,
    p_source_digest, p_output_digest, p_actor_id, p_request_fingerprint
  );
  update public.dice_live_matches
  set deleted_at = now(), deleted_by = p_deleted_by
  where id = p_match_id
    and official_result_id = (p_game->>'id')::uuid
    and deleted_at is null;
  get diagnostics affected = row_count;
  if affected = 0
     and committed->>'replayed' = 'true'
     and exists (
       select 1 from public.dice_live_matches
       where id = p_match_id
         and official_result_id = (p_game->>'id')::uuid
         and deleted_at is not null
         and deleted_by = p_deleted_by
     ) then
    return committed;
  end if;
  if affected <> 1 then
    raise exception using errcode = '40001', message = 'dice_live.delete_source_changed';
  end if;
  return committed;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_delete_with_rating_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,uuid,uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_events_immutable()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  raise exception using
    errcode = '55000',
    message = 'dice_live.events_append_only',
    detail = 'live event rows may only be inserted by the append command';
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_events_immutable() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_events_immutable() TO PUBLIC;

GRANT EXECUTE ON FUNCTION public.dice_live_events_immutable() TO anon;

GRANT EXECUTE ON FUNCTION public.dice_live_events_immutable() TO authenticated;

GRANT EXECUTE ON FUNCTION public.dice_live_events_immutable() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_materialize_result(p_match_id uuid, p_projection jsonb, p_status text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  m public.dice_live_matches%rowtype;
  result_id uuid;
  team text;
  player text;
  team_index integer;
  winner integer;
  delta integer;
  summary jsonb;
  stats_snapshot jsonb;
begin
  select * into m from public.dice_live_matches where id = p_match_id;
  stats_snapshot := jsonb_build_object(
    'schema_version', 'dice-recorded-stats/v1',
    'coverage', coalesce(p_projection->>'coverage', 'unknown'),
    'observations', coalesce((p_projection->>'observations')::integer, 0),
    'outcomes', coalesce(p_projection->'stats', '{}'::jsonb),
    'players', coalesce(p_projection->'player_stats', '{}'::jsonb)
  );
  if p_status = 'completed' then
    winner := case
      when (p_projection->'score'->>0)::integer > (p_projection->'score'->>1)::integer then 1
      when (p_projection->'score'->>1)::integer > (p_projection->'score'->>0)::integer then 2
      else null
    end;
    result_id := m.official_result_id;
    if result_id is null then
      insert into public.dice_games
        (created_by, ranked, team1_score, team2_score, winner_team, played_at,
         source_live_match_id, live_result_state, termination_reason, detail_coverage,
         stats_complete, recorded_stats)
      values (m.created_by, m.ranked, (p_projection->'score'->>0)::integer,
        (p_projection->'score'->>1)::integer, winner, now(), m.id, 'official',
        p_projection->>'termination_reason', p_projection->>'coverage',
        (p_projection->>'coverage') = 'complete', stats_snapshot) returning id into result_id;
      update public.dice_live_matches set official_result_id = result_id where id = m.id;
      delta := 1;
    else
      select live_result_state into team from public.dice_games where id = result_id;
      update public.dice_games set team1_score = (p_projection->'score'->>0)::integer,
        team2_score = (p_projection->'score'->>1)::integer, winner_team = winner,
        live_result_state = 'official', termination_reason = p_projection->>'termination_reason',
        detail_coverage = p_projection->>'coverage',
        stats_complete = (p_projection->>'coverage') = 'complete',
        recorded_stats = stats_snapshot
        where id = result_id;
      delta := case when team = 'reopened' then 1 else 0 end;
    end if;
    if delta <> 0 then
      for team_index in 0..1 loop
        team := m.team_order->>team_index;
        if delta = 1 then
          insert into public.dice_game_players (game_id, user_id, team, self_sinks, sinks)
            select result_id, value::uuid, team_index + 1, 0, 0
              from jsonb_array_elements_text(m.teams->team) on conflict (game_id, user_id) do nothing;
        end if;
        update public.dice_profiles set
          games_played = games_played + delta,
          wins = wins + case when winner is not null and team_index + 1 = winner then delta else 0 end,
          losses = losses + case when winner is not null and team_index + 1 <> winner then delta else 0 end,
          normal_wins = normal_wins + case when winner is not null and team_index + 1 = winner then delta else 0 end,
          normal_losses = normal_losses + case when winner is not null and team_index + 1 <> winner then delta else 0 end
        where user_id in (select value::uuid from jsonb_array_elements_text(m.teams->team));
      end loop;
    end if;
  elsif m.official_result_id is not null then
    select live_result_state into team from public.dice_games where id = m.official_result_id;
    if team = 'official' then
      result_id := m.official_result_id;
      winner := (select winner_team from public.dice_games where id = result_id);
      for team_index in 0..1 loop
        team := m.team_order->>team_index;
        update public.dice_profiles set
          games_played = greatest(0, games_played - 1),
          wins = greatest(0, wins - case when team_index + 1 = winner then 1 else 0 end),
          losses = greatest(0, losses - case when team_index + 1 <> winner then 1 else 0 end),
          normal_wins = greatest(0, normal_wins - case when team_index + 1 = winner then 1 else 0 end),
          normal_losses = greatest(0, normal_losses - case when team_index + 1 <> winner then 1 else 0 end)
        where user_id in (select value::uuid from jsonb_array_elements_text(m.teams->team));
      end loop;
      update public.dice_games set live_result_state = 'reopened' where id = result_id;
    end if;
  end if;
  if result_id is null then return null; end if;
  select jsonb_build_object('id', id, 'source_live_match_id', source_live_match_id,
    'score', jsonb_build_array(team1_score, team2_score), 'winner_team', winner_team,
    'state', live_result_state, 'termination_reason', termination_reason,
    'detail_coverage', detail_coverage, 'stats_complete', stats_complete)
    into summary from public.dice_games where id = result_id;
  return summary;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_materialize_result(uuid,jsonb,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_materialize_result(uuid,jsonb,text) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_prediction_snapshot_immutable()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if old.prediction_snapshot is distinct from new.prediction_snapshot then
    raise exception 'prediction_snapshot is immutable' using errcode = '22023';
  end if;
  return new;
end
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_prediction_snapshot_immutable() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_prediction_snapshot_immutable() TO PUBLIC;

GRANT EXECUTE ON FUNCTION public.dice_live_prediction_snapshot_immutable() TO anon;

GRANT EXECUTE ON FUNCTION public.dice_live_prediction_snapshot_immutable() TO authenticated;

GRANT EXECUTE ON FUNCTION public.dice_live_prediction_snapshot_immutable() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_result_write_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if old.source_live_match_id is not null
     and current_setting('dice.live_materialization', true) is distinct from 'on'
     and current_setting('dice.rating_mutation', true) is distinct from 'on' then
    raise exception using errcode = '55000', message = 'dice_live.result_managed_by_live_match';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_result_write_guard() FROM PUBLIC, anon, authenticated, service_role;

COMMENT ON FUNCTION public.dice_live_result_write_guard() IS 'Live projections may only be changed by live materialization or canonical rating mutation.';

CREATE OR REPLACE FUNCTION public.dice_live_set_ranked(p_match_id uuid, p_ranked boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '2s'
AS $function$
declare
  v_result_id uuid;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:canonical', 0)
  );
  select official_result_id into v_result_id
  from public.dice_live_matches
  where id = p_match_id and deleted_at is null
  for update;
  if not found then
    return jsonb_build_object('status', 'missing');
  end if;
  if v_result_id is not null then
    return jsonb_build_object('status', 'official');
  end if;
  update public.dice_live_matches
  set ranked = p_ranked
  where id = p_match_id;
  return jsonb_build_object('status', 'updated');
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_set_ranked(uuid,boolean) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_live_set_ranked(uuid,boolean) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_live_sync_ranked_from_result()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if new.source_live_match_id is not null then
    update public.dice_live_matches
    set ranked = new.ranked
    where id = new.source_live_match_id;
  end if;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_sync_ranked_from_result() FROM PUBLIC, anon, authenticated, service_role;

COMMENT ON FUNCTION public.dice_live_sync_ranked_from_result() IS 'Keeps a materialized live result and its source match ranked flag atomic.';

CREATE OR REPLACE FUNCTION public.dice_live_track_rating_repair()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if tg_op = 'DELETE' then
    if old.source_live_match_id is not null then
      delete from public.dice_live_rating_repairs
      where match_id = old.source_live_match_id;
    end if;
    return old;
  end if;
  if new.source_live_match_id is null then
    return new;
  end if;
  if current_setting('dice.rating_mutation', true) = 'on' then
    delete from public.dice_live_rating_repairs
    where match_id = new.source_live_match_id;
  elsif current_setting('dice.live_materialization', true) = 'on' then
    if new.ranked and new.live_result_state in ('official', 'reopened') then
      insert into public.dice_live_rating_repairs (match_id)
      values (new.source_live_match_id)
      on conflict (match_id) do update set updated_at = now();
    else
      delete from public.dice_live_rating_repairs
      where match_id = new.source_live_match_id;
    end if;
  end if;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_live_track_rating_repair() FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_analytics_snapshot()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
  select jsonb_build_object(
    'snapshot_version', 'dice-rating-analytics/v1',
    'profiles', coalesce((
      select jsonb_agg(jsonb_build_object(
        'user_id', p.user_id, 'display_name', p.display_name,
        'avatar_url', p.avatar_url,
        'elo_rating', p.elo_rating, 'rating_deviation', p.rating_deviation,
        'elo_model_version', p.elo_model_version,
        'ranked_games_played', p.ranked_games_played,
        'games_played', p.games_played, 'wins', p.wins, 'losses', p.losses,
        'ranked_wins', p.ranked_wins, 'ranked_losses', p.ranked_losses,
        'normal_wins', p.normal_wins, 'normal_losses', p.normal_losses,
        'self_sinks', p.self_sinks, 'sinks', p.sinks,
        'hide_from_leaderboard', p.hide_from_leaderboard
      ) order by p.user_id)
      from public.dice_profiles p
    ), '[]'::jsonb),
    'games', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', g.id, 'ranked', g.ranked, 'duo_only', g.duo_only,
        'winner_team', g.winner_team, 'team1_score', g.team1_score,
        'team2_score', g.team2_score, 'played_at', g.played_at,
        'created_at', g.created_at, 'live_result_state', g.live_result_state
      ) order by g.played_at, g.created_at, g.id)
      from public.dice_games g
      where (g.live_result_state is null or g.live_result_state = 'official')
        and g.duo_only is not true
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', gp.id, 'game_id', gp.game_id, 'user_id', gp.user_id,
        'team', gp.team, 'self_sinks', gp.self_sinks, 'sinks', gp.sinks,
        'elo_before', gp.elo_before, 'elo_after', gp.elo_after,
        'rating_deviation_before', gp.rating_deviation_before,
        'rating_deviation_after', gp.rating_deviation_after
      ) order by gp.game_id, gp.user_id, gp.id)
      from public.dice_game_players gp
      join public.dice_games g on g.id = gp.game_id
      where (g.live_result_state is null or g.live_result_state = 'official')
        and g.duo_only is not true
    ), '[]'::jsonb)
  )
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_analytics_snapshot() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_analytics_snapshot() TO anon;

GRANT EXECUTE ON FUNCTION public.dice_rating_analytics_snapshot() TO authenticated;

GRANT EXECUTE ON FUNCTION public.dice_rating_analytics_snapshot() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_apply_game_mutation_if_current(p_mutation_id uuid, p_source jsonb, p_operation text, p_game jsonb, p_players jsonb, p_expected_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb, p_source_digest text, p_output_digest text, p_actor_id text, p_request_fingerprint text, p_expected_updated_at timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', ''
  ) <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_operation is distinct from 'update' or p_expected_updated_at is null then
    raise exception using errcode = '22023', message = 'dice_game.invalid_update_revision';
  end if;

  perform pg_catalog.set_config(
    'dice.game_expected_updated_at', p_expected_updated_at::text, true
  );
  return public.dice_rating_apply_game_mutation(
    p_mutation_id, p_source, p_operation, p_game, p_players,
    p_expected_source, p_player_snapshots, p_profile_states,
    p_source_digest, p_output_digest, p_actor_id, p_request_fingerprint
  );
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_apply_game_mutation_if_current(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text,timestamp with time zone) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_apply_game_mutation_unchecked(p_source jsonb, p_operation text, p_game jsonb, p_players jsonb, p_expected_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  v_game_id uuid;
  affected_games integer;
  committed jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_operation is null
     or p_operation not in ('create', 'update', 'delete')
     or p_source is null
     or p_game is null
     or p_expected_source is null
     or jsonb_typeof(p_source) <> 'object'
     or jsonb_typeof(p_game) <> 'object'
     or jsonb_typeof(p_expected_source) <> 'object'
     or not (p_game ? 'id')
     or jsonb_typeof(p_game->'id') <> 'string' then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_mutation_payload';
  end if;
  v_game_id := (p_game->>'id')::uuid;

  if p_operation in ('create', 'update') and (
    p_players is null
    or jsonb_typeof(p_players) <> 'array'
    or jsonb_array_length(p_players) not in (2, 4)
    or not (p_game ?& array[
      'created_by', 'ranked', 'team1_score', 'team2_score', 'winner_team',
      'played_at', 'created_at', 'tournament_id'
    ])
    or exists (
      select 1 from jsonb_array_elements(p_players) item
      where jsonb_typeof(item) <> 'object'
         or not (item ?& array[
           'id', 'user_id', 'team', 'counts_for_group_stage', 'self_sinks', 'sinks'
         ])
    )
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_mutation_values';
  end if;
  if p_operation in ('create', 'update') and (
    (select count(*) from jsonb_array_elements(p_players) item where (item->>'team')::integer = 1)
      <> jsonb_array_length(p_players) / 2
    or (select count(*) from jsonb_array_elements(p_players) item where (item->>'team')::integer = 2)
      <> jsonb_array_length(p_players) / 2
    or (p_game->>'team1_score')::integer = (p_game->>'team2_score')::integer
    or (p_game->>'winner_team')::integer is distinct from case
      when (p_game->>'team1_score')::integer > (p_game->>'team2_score')::integer then 1
      else 2
    end
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_game_result';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:canonical', 0)
  );
  lock table public.dice_games, public.dice_game_players, public.dice_profiles in share row exclusive mode;

  if public.dice_rating_source_snapshot() is distinct from p_source then
    raise exception using errcode = '40001', message = 'dice_rating.source_changed';
  end if;

  if p_operation = 'create' then
    insert into public.dice_games (
      id, created_by, ranked, team1_score, team2_score, winner_team,
      played_at, created_at, updated_at, tournament_id
    ) values (
      v_game_id,
      (p_game->>'created_by')::uuid,
      (p_game->>'ranked')::boolean,
      (p_game->>'team1_score')::integer,
      (p_game->>'team2_score')::integer,
      (p_game->>'winner_team')::integer,
      (p_game->>'played_at')::timestamptz,
      (p_game->>'created_at')::timestamptz,
      (p_game->>'created_at')::timestamptz,
      (p_game->>'tournament_id')::uuid
    );
  elsif p_operation = 'update' then
    update public.dice_games set
      ranked = (p_game->>'ranked')::boolean,
      team1_score = (p_game->>'team1_score')::integer,
      team2_score = (p_game->>'team2_score')::integer,
      winner_team = (p_game->>'winner_team')::integer,
      played_at = (p_game->>'played_at')::timestamptz,
      updated_at = now(),
      tournament_id = (p_game->>'tournament_id')::uuid
    where id = v_game_id;
    get diagnostics affected_games = row_count;
    if affected_games <> 1 then
      raise exception using errcode = 'P0002', message = 'dice_rating.game_not_found';
    end if;
    delete from public.dice_game_players gp where gp.game_id = v_game_id;
  else
    delete from public.dice_games where id = v_game_id;
    get diagnostics affected_games = row_count;
    if affected_games <> 1 then
      raise exception using errcode = 'P0002', message = 'dice_rating.game_not_found';
    end if;
  end if;

  if p_operation in ('create', 'update') then
    insert into public.dice_game_players (
      id, game_id, user_id, team, counts_for_group_stage, self_sinks, sinks
    )
    select player.id, v_game_id, player.user_id, player.team,
      player.counts_for_group_stage, player.self_sinks, player.sinks
    from jsonb_to_recordset(p_players) as player(
      id uuid,
      user_id uuid,
      team integer,
      counts_for_group_stage boolean,
      self_sinks integer,
      sinks integer
    );
  end if;

  if public.dice_rating_source_snapshot() is distinct from p_expected_source then
    raise exception using errcode = '40001', message = 'dice_rating.post_mutation_mismatch';
  end if;

  committed := public.dice_rating_commit(
    p_expected_source, p_player_snapshots, p_profile_states
  );
  return jsonb_build_object('operation', p_operation, 'game_id', v_game_id) || committed;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb) FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_apply_game_mutation(p_mutation_id uuid, p_source jsonb, p_operation text, p_game jsonb, p_players jsonb, p_expected_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb, p_source_digest text, p_output_digest text, p_actor_id text, p_request_fingerprint text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  committed jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_mutation_id is null then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_mutation_id';
  end if;
  if p_source_digest is null
     or p_output_digest is null
     or p_source_digest !~ '^[0-9a-f]{64}$'
     or p_output_digest !~ '^[0-9a-f]{64}$' then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_mutation_digest';
  end if;
  if p_operation = 'create' and (
    p_actor_id is null
    or p_request_fingerprint is null
    or p_request_fingerprint !~ '^[0-9a-f]{64}$'
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_idempotency_binding';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:rating:mutation:' || p_mutation_id::text, 0)
  );
  select jsonb_build_object(
    'operation', r.operation,
    'game_id', r.game_id,
    'players_updated', r.players_updated,
    'profiles_updated', r.profiles_updated,
    'source_digest', r.source_digest,
    'output_digest', r.output_digest,
    'mutation_id', r.mutation_id,
    'actor_id', r.actor_id,
    'request_fingerprint', r.request_fingerprint,
    'replayed', true
  ) into committed
  from public.dice_rating_mutation_receipts r
  where r.mutation_id = p_mutation_id;
  if committed is not null then
    if committed->>'operation' is distinct from p_operation
       or committed->>'game_id' is distinct from p_game->>'id'
       or committed->>'actor_id' is distinct from p_actor_id
       or committed->>'request_fingerprint' is distinct from p_request_fingerprint then
      raise exception using errcode = '23505', message = 'dice_rating.idempotency_conflict';
    end if;
    return committed;
  end if;

  perform pg_catalog.set_config('dice.rating_mutation', 'on', true);
  committed := public.dice_rating_apply_game_mutation_unchecked(
    p_source, p_operation, p_game, p_players, p_expected_source,
    p_player_snapshots, p_profile_states
  );
  insert into public.dice_rating_mutation_receipts (
    mutation_id, operation, game_id, actor_id, request_fingerprint,
    source_digest, output_digest, players_updated, profiles_updated
  ) values (
    p_mutation_id, p_operation, (p_game->>'id')::uuid,
    p_actor_id, p_request_fingerprint, p_source_digest, p_output_digest,
    (committed->>'players_updated')::integer,
    (committed->>'profiles_updated')::integer
  );
  return committed || jsonb_build_object(
    'mutation_id', p_mutation_id,
    'actor_id', p_actor_id,
    'request_fingerprint', p_request_fingerprint,
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text) TO service_role;

COMMENT ON FUNCTION public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text) IS 'Atomic canonical game and rating mutation with idempotency receipt.';

CREATE OR REPLACE FUNCTION public.dice_rating_commit_rebuild(p_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  return public.dice_rating_commit(p_source, p_player_snapshots, p_profile_states);
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_commit(p_source jsonb, p_player_snapshots jsonb, p_profile_states jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  expected_players integer;
  expected_profiles integer;
  updated_players integer;
  updated_profiles integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_source is null
     or p_player_snapshots is null
     or p_profile_states is null
     or jsonb_typeof(p_source) <> 'object'
     or jsonb_typeof(p_source->'players') <> 'array'
     or jsonb_typeof(p_source->'profiles') <> 'array'
     or jsonb_typeof(p_source->'games') <> 'array'
     or jsonb_typeof(p_player_snapshots) <> 'array'
     or jsonb_typeof(p_profile_states) <> 'array' then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_commit_payload';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:canonical', 0)
  );
  lock table public.dice_games, public.dice_game_players, public.dice_profiles
    in share row exclusive mode;

  if public.dice_rating_source_snapshot() is distinct from p_source then
    raise exception using errcode = '40001', message = 'dice_rating.source_changed';
  end if;

  expected_players := jsonb_array_length(p_source->'players');
  expected_profiles := jsonb_array_length(p_source->'profiles');
  if jsonb_array_length(p_player_snapshots) <> expected_players
     or jsonb_array_length(p_profile_states) <> expected_profiles then
    raise exception using errcode = '22023', message = 'dice_rating.incomplete_state';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_player_snapshots) item
    where jsonb_typeof(item) <> 'object'
       or not (item ?& array[
         'id', 'elo_before', 'elo_after',
         'rating_deviation_before', 'rating_deviation_after'
       ])
       or jsonb_typeof(item->'id') <> 'string'
       or jsonb_typeof(item->'elo_before') not in ('number', 'null')
       or jsonb_typeof(item->'elo_after') not in ('number', 'null')
       or jsonb_typeof(item->'rating_deviation_before') not in ('number', 'null')
       or jsonb_typeof(item->'rating_deviation_after') not in ('number', 'null')
       or (
         (jsonb_typeof(item->'elo_before') = 'number')::integer
         + (jsonb_typeof(item->'elo_after') = 'number')::integer
         + (jsonb_typeof(item->'rating_deviation_before') = 'number')::integer
         + (jsonb_typeof(item->'rating_deviation_after') = 'number')::integer
       ) not in (0, 4)
  ) or exists (
    select 1
    from jsonb_array_elements(p_profile_states) item
    where jsonb_typeof(item) <> 'object'
       or not (item ?& array[
         'user_id', 'elo_rating', 'rating_deviation',
         'ranked_games_played', 'games_played', 'wins', 'losses',
         'ranked_wins', 'ranked_losses', 'normal_wins', 'normal_losses',
         'self_sinks', 'sinks'
       ])
       or jsonb_typeof(item->'user_id') <> 'string'
       or exists (
         select 1 from unnest(array[
           'elo_rating', 'rating_deviation', 'ranked_games_played',
           'games_played', 'wins', 'losses', 'ranked_wins', 'ranked_losses',
           'normal_wins', 'normal_losses', 'self_sinks', 'sinks'
         ]) field_name
         where jsonb_typeof(item->field_name) <> 'number'
       )
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_state_values';
  end if;
  if exists (
    with source_players as (
      select *
      from jsonb_to_recordset(p_source->'players') as row_data(
        id uuid, game_id uuid, team integer
      )
    ), source_games as (
      select *
      from jsonb_to_recordset(p_source->'games') as row_data(
        id uuid, ranked boolean, winner_team integer, live_result_state text
      )
    ), rosters as (
      select game_id,
        count(*) filter (where team = 1) as team1_players,
        count(*) filter (where team = 2) as team2_players
      from source_players
      group by game_id
    )
    select 1
    from jsonb_to_recordset(p_player_snapshots) as snapshot(
      id uuid, elo_before integer
    )
    join source_players player on player.id = snapshot.id
    join source_games game on game.id = player.game_id
    join rosters roster on roster.game_id = game.id
    where (snapshot.elo_before is not null) is distinct from coalesce((
      game.ranked
      and game.winner_team in (1, 2)
      and game.live_result_state is distinct from 'reopened'
      and roster.team1_players > 0
      and roster.team1_players = roster.team2_players
    ), false)
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.snapshot_eligibility_mismatch';
  end if;
  if exists (
    select 1
    from jsonb_to_recordset(p_profile_states) as state(
      ranked_games_played integer,
      games_played integer,
      wins integer,
      losses integer,
      ranked_wins integer,
      ranked_losses integer,
      normal_wins integer,
      normal_losses integer,
      self_sinks integer,
      sinks integer
    )
    where state.ranked_games_played < 0
       or state.games_played < 0
       or state.wins < 0
       or state.losses < 0
       or state.ranked_wins < 0
       or state.ranked_losses < 0
       or state.normal_wins < 0
       or state.normal_losses < 0
       or state.self_sinks < 0
       or state.sinks < 0
       or state.wins <> state.ranked_wins + state.normal_wins
       or state.losses <> state.ranked_losses + state.normal_losses
       or state.wins + state.losses > state.games_played
       or state.ranked_wins + state.ranked_losses <> state.ranked_games_played
       or state.ranked_games_played > state.games_played
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_aggregate';
  end if;

  if exists (
    (select row_data.id
       from jsonb_to_recordset(p_player_snapshots) as row_data(id uuid)
     except
     select row_data.id
       from jsonb_to_recordset(p_source->'players') as row_data(id uuid))
    union all
    (select row_data.id
       from jsonb_to_recordset(p_source->'players') as row_data(id uuid)
     except
     select row_data.id
       from jsonb_to_recordset(p_player_snapshots) as row_data(id uuid))
  ) or exists (
    (select row_data.user_id
       from jsonb_to_recordset(p_profile_states) as row_data(user_id uuid)
     except
     select row_data.user_id
       from jsonb_to_recordset(p_source->'profiles') as row_data(user_id uuid))
    union all
    (select row_data.user_id
       from jsonb_to_recordset(p_source->'profiles') as row_data(user_id uuid)
     except
     select row_data.user_id
       from jsonb_to_recordset(p_profile_states) as row_data(user_id uuid))
  ) then
    raise exception using errcode = '22023', message = 'dice_rating.state_identity_mismatch';
  end if;

  update public.dice_game_players gp set
    elo_before = snapshot.elo_before,
    elo_after = snapshot.elo_after,
    rating_deviation_before = snapshot.rating_deviation_before,
    rating_deviation_after = snapshot.rating_deviation_after
  from jsonb_to_recordset(p_player_snapshots) as snapshot(
    id uuid,
    elo_before integer,
    elo_after integer,
    rating_deviation_before numeric,
    rating_deviation_after numeric
  )
  where gp.id = snapshot.id;
  get diagnostics updated_players = row_count;

  update public.dice_profiles profile set
    elo_rating = state.elo_rating,
    rating_deviation = state.rating_deviation,
    elo_model_version = '1.1.0',
    ranked_games_played = state.ranked_games_played,
    games_played = state.games_played,
    wins = state.wins,
    losses = state.losses,
    ranked_wins = state.ranked_wins,
    ranked_losses = state.ranked_losses,
    normal_wins = state.normal_wins,
    normal_losses = state.normal_losses,
    self_sinks = state.self_sinks,
    sinks = state.sinks
  from jsonb_to_recordset(p_profile_states) as state(
    user_id uuid,
    elo_rating integer,
    rating_deviation numeric,
    ranked_games_played integer,
    games_played integer,
    wins integer,
    losses integer,
    ranked_wins integer,
    ranked_losses integer,
    normal_wins integer,
    normal_losses integer,
    self_sinks integer,
    sinks integer
  )
  where profile.user_id = state.user_id;
  get diagnostics updated_profiles = row_count;

  if updated_players <> expected_players or updated_profiles <> expected_profiles then
    raise exception using errcode = 'P0001', message = 'dice_rating.commit_row_count_mismatch';
  end if;

  return jsonb_build_object(
    'players_updated', updated_players,
    'profiles_updated', updated_profiles,
    'state', public.dice_rating_state_snapshot()
  );
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_commit(jsonb,jsonb,jsonb) FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_mutation_receipt(p_mutation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare
  receipt jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  select jsonb_build_object(
    'mutation_id', r.mutation_id,
    'operation', r.operation,
    'game_id', r.game_id,
    'actor_id', r.actor_id,
    'request_fingerprint', r.request_fingerprint,
    'source_digest', r.source_digest,
    'output_digest', r.output_digest,
    'players_updated', r.players_updated,
    'profiles_updated', r.profiles_updated
  ) into receipt
  from public.dice_rating_mutation_receipts r
  where r.mutation_id = p_mutation_id;
  return receipt;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_mutation_receipt(uuid) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_mutation_receipt(uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_source_snapshot()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
  select jsonb_build_object(
    'profiles', coalesce((
      select jsonb_agg(jsonb_build_object('user_id', p.user_id) order by p.user_id)
      from public.dice_profiles p
    ), '[]'::jsonb),
    'games', coalesce((
      select jsonb_agg(to_jsonb(source) order by source.played_at, source.created_at, source.id)
      from (
        select g.id, g.created_by, g.ranked, g.team1_score, g.team2_score,
          g.winner_team, g.played_at, g.created_at, g.tournament_id,
          g.source_live_match_id, g.live_result_state, g.termination_reason,
          g.detail_coverage, g.stats_complete
        from public.dice_games g
        where g.duo_only is not true
      ) source
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(to_jsonb(source) order by source.game_id, source.user_id, source.id)
      from (
        select gp.id, gp.game_id, gp.user_id, gp.team,
          gp.counts_for_group_stage, gp.self_sinks, gp.sinks
        from public.dice_game_players gp
        join public.dice_games g on g.id = gp.game_id
        where g.duo_only is not true
      ) source
    ), '[]'::jsonb)
  )
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_source_snapshot() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_source_snapshot() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_rating_state_snapshot()
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
  select jsonb_build_object(
    'profiles', coalesce((
      select jsonb_agg(jsonb_build_object(
        'user_id', p.user_id,
        'elo_rating', p.elo_rating,
        'rating_deviation', p.rating_deviation,
        'elo_model_version', p.elo_model_version,
        'ranked_games_played', p.ranked_games_played,
        'games_played', p.games_played,
        'wins', p.wins,
        'losses', p.losses,
        'ranked_wins', p.ranked_wins,
        'ranked_losses', p.ranked_losses,
        'normal_wins', p.normal_wins,
        'normal_losses', p.normal_losses,
        'self_sinks', p.self_sinks,
        'sinks', p.sinks
      ) order by p.user_id)
      from public.dice_profiles p
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', gp.id,
        'elo_before', gp.elo_before,
        'elo_after', gp.elo_after,
        'rating_deviation_before', gp.rating_deviation_before,
        'rating_deviation_after', gp.rating_deviation_after
      ) order by gp.id)
      from public.dice_game_players gp
      join public.dice_games g on g.id = gp.game_id
      where g.duo_only is not true
    ), '[]'::jsonb)
  )
$function$
;

REVOKE ALL ON FUNCTION public.dice_rating_state_snapshot() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_rating_state_snapshot() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_virtual_immutable_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
begin
  raise exception using errcode = '55000', message = 'dice_virtual.ledger_append_only';
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_virtual_immutable_guard() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_virtual_immutable_guard() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_virtual_locked_terms_guard()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
begin
  if new.tournament_id <> old.tournament_id or new.market_id <> old.market_id
     or new.user_id <> old.user_id or new.client_pick_id <> old.client_pick_id
     or new.selection <> old.selection or new.stake <> old.stake
     or new.potential_return <> old.potential_return
     or new.locked_probability_millionths <> old.locked_probability_millionths
     or new.quote_model_id <> old.quote_model_id
     or new.quote_model_version <> old.quote_model_version
     or new.quote_match_version <> old.quote_match_version then
    raise exception using errcode = '55000', message = 'dice_virtual.quote_terms_immutable';
  end if;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_virtual_locked_terms_guard() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_virtual_locked_terms_guard() TO service_role;

CREATE OR REPLACE FUNCTION public.dice_virtual_open_bankroll(p_tournament_id uuid, p_user_id uuid, p_amount integer DEFAULT 1000)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare balance integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  if p_amount <= 0 then raise exception using errcode = '22023', message = 'dice_virtual.invalid_grant'; end if;
  if not exists (select 1 from public.dice_tournament_enrollments where tournament_id = p_tournament_id and user_id = p_user_id) then
    raise exception using errcode = '42501', message = 'dice_virtual.not_enrolled';
  end if;
  insert into public.dice_virtual_ledger (tournament_id, user_id, kind, amount, operation_key)
    values (p_tournament_id, p_user_id, 'opening_grant', p_amount, 'opening_grant')
    on conflict (tournament_id, user_id, operation_key) do nothing;
  select coalesce(sum(amount), 0)::integer into balance from public.dice_virtual_ledger
   where tournament_id = p_tournament_id and user_id = p_user_id;
  return balance;
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_virtual_open_bankroll(uuid,uuid,integer) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_virtual_open_bankroll(uuid,uuid,integer) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_virtual_place_pick(p_tournament_id uuid, p_market_id bigint, p_user_id uuid, p_client_pick_id text, p_selection text, p_stake integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  m public.dice_virtual_markets%rowtype;
  existing public.dice_virtual_picks%rowtype;
  probability integer;
  return_amount integer;
  balance integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  if p_stake <= 0 then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_stake';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_tournament_id::text || ':' || p_user_id::text, 0));
  select * into existing from public.dice_virtual_picks
   where tournament_id = p_tournament_id and user_id = p_user_id and client_pick_id = p_client_pick_id;
  if found then
    if existing.market_id = p_market_id and existing.selection = p_selection and existing.stake = p_stake then
      return to_jsonb(existing);
    end if;
    raise exception using errcode = 'P0001', message = 'dice_virtual.pick_id_conflict';
  end if;
  select * into m from public.dice_virtual_markets where id = p_market_id and tournament_id = p_tournament_id for update;
  if not found then raise exception using errcode = 'P0001', message = 'dice_virtual.market_not_found'; end if;
  if m.status <> 'open' then raise exception using errcode = 'P0001', message = 'dice_virtual.market_closed'; end if;
  probability := (m.selections->p_selection->>'probability_millionths')::integer;
  if probability is null or probability not between 1 and 999999 then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_selection';
  end if;
  select coalesce(sum(amount), 0) into balance from public.dice_virtual_ledger
   where tournament_id = p_tournament_id and user_id = p_user_id;
  if balance < p_stake then raise exception using errcode = 'P0001', message = 'dice_virtual.insufficient_balance'; end if;
  return_amount := floor((p_stake::numeric * 1000000) / probability)::integer;
  insert into public.dice_virtual_picks (
    tournament_id, market_id, user_id, client_pick_id, selection, stake,
    potential_return, locked_probability_millionths, quote_model_id,
    quote_model_version, quote_match_version
  ) values (
    p_tournament_id, p_market_id, p_user_id, p_client_pick_id, p_selection, p_stake,
    return_amount, probability, m.model_id, m.model_version, m.match_version
  ) returning * into existing;
  insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
    values (p_tournament_id, p_user_id, existing.id, 'stake_debit', -p_stake, 'pick:' || existing.id || ':stake');
  return to_jsonb(existing);
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_virtual_place_pick(uuid,bigint,uuid,text,text,integer) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_virtual_place_pick(uuid,bigint,uuid,text,text,integer) TO service_role;

CREATE OR REPLACE FUNCTION public.dice_virtual_settle_market(p_market_id bigint, p_winner_selection text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  m public.dice_virtual_markets%rowtype;
  p public.dice_virtual_picks%rowtype;
  prior_credit integer;
  credit integer;
  revision integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_virtual.service_role_required';
  end if;
  select * into m from public.dice_virtual_markets where id = p_market_id for update;
  if not found then raise exception using errcode = 'P0001', message = 'dice_virtual.market_not_found'; end if;
  if m.status = 'settled' and m.settled_selection is not distinct from p_winner_selection then
    return jsonb_build_object('market_id', m.id, 'settlement_revision', m.settlement_revision);
  end if;
  if p_winner_selection is not null and not (m.selections ? p_winner_selection) then
    raise exception using errcode = '22023', message = 'dice_virtual.invalid_selection';
  end if;
  revision := m.settlement_revision + 1;
  for p in select * from public.dice_virtual_picks where market_id = m.id for update loop
    select coalesce(sum(amount), 0)::integer into prior_credit
      from public.dice_virtual_ledger where pick_id = p.id and kind in ('payout_credit', 'refund_credit', 'settlement_reversal');
    if prior_credit <> 0 then
      insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
        values (p.tournament_id, p.user_id, p.id, 'settlement_reversal', -prior_credit,
          'pick:' || p.id || ':settlement:' || revision || ':reversal');
    end if;
    credit := case when p_winner_selection is null then p.stake when p.selection = p_winner_selection then p.potential_return else 0 end;
    if credit > 0 then
      insert into public.dice_virtual_ledger (tournament_id, user_id, pick_id, kind, amount, operation_key)
        values (p.tournament_id, p.user_id, p.id,
          case when p_winner_selection is null then 'refund_credit' else 'payout_credit' end,
          credit, 'pick:' || p.id || ':settlement:' || revision || ':credit');
    end if;
    update public.dice_virtual_picks set
      status = case when p_winner_selection is null then 'void' when p.selection = p_winner_selection then 'won' else 'lost' end,
      settled_at = now() where id = p.id;
  end loop;
  update public.dice_virtual_markets set status = 'settled', settled_at = now(),
    settled_selection = p_winner_selection, settlement_revision = revision where id = m.id;
  return jsonb_build_object('market_id', m.id, 'settlement_revision', revision, 'winner_selection', p_winner_selection);
end;
$function$
;

REVOKE ALL ON FUNCTION public.dice_virtual_settle_market(bigint,text) FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.dice_virtual_settle_market(bigint,text) TO service_role;

DROP TRIGGER IF EXISTS dice_live_sync_ranked_from_result ON public.dice_games;

CREATE TRIGGER dice_live_sync_ranked_from_result AFTER UPDATE OF ranked ON public.dice_games FOR EACH ROW EXECUTE FUNCTION dice_live_sync_ranked_from_result();

DROP TRIGGER IF EXISTS dice_live_track_rating_repair ON public.dice_games;

CREATE TRIGGER dice_live_track_rating_repair AFTER INSERT OR DELETE OR UPDATE ON public.dice_games FOR EACH ROW EXECUTE FUNCTION dice_live_track_rating_repair();

DROP TRIGGER IF EXISTS dice_game_reject_stale_update ON public.dice_games;

CREATE TRIGGER dice_game_reject_stale_update BEFORE UPDATE ON public.dice_games FOR EACH ROW EXECUTE FUNCTION dice_game_reject_stale_update();

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.dice_feature_access'::regclass AND conname='dice_feature_access_released_check') THEN ALTER TABLE public.dice_feature_access ADD CONSTRAINT dice_feature_access_released_check CHECK (enabled); END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_match_id_referee_id_operation_id_key') THEN ALTER TABLE public.dice_live_command_metrics ADD CONSTRAINT dice_live_command_metrics_match_id_referee_id_operation_id_key UNIQUE (match_id, referee_id, operation_id); END IF; END $$;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.dice_live_command_metrics'::regclass AND conname='dice_live_command_metrics_referee_id_fkey') THEN ALTER TABLE public.dice_live_command_metrics ADD CONSTRAINT dice_live_command_metrics_referee_id_fkey FOREIGN KEY (referee_id) REFERENCES dice_profiles(user_id) ON DELETE CASCADE; END IF; END $$;

ALTER TABLE public.dice_feature_access ALTER COLUMN enabled SET DEFAULT true;

DROP POLICY IF EXISTS dice_games_public_read ON public.dice_games;

CREATE POLICY dice_games_public_read ON public.dice_games FOR SELECT TO anon, authenticated USING ((((live_result_state IS NULL) OR (live_result_state = 'official'::text)) AND (duo_only IS NOT TRUE)));

DROP POLICY IF EXISTS dice_game_players_public_read ON public.dice_game_players;

CREATE POLICY dice_game_players_public_read ON public.dice_game_players FOR SELECT TO anon, authenticated USING ((EXISTS ( SELECT 1
   FROM dice_games g
  WHERE ((g.id = dice_game_players.game_id) AND (g.duo_only IS NOT TRUE)))));

-- A copied version ledger alone is not release readiness.
CREATE OR REPLACE FUNCTION public.dice_release_readiness()
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $readiness$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.dice_schema_migrations WHERE version=79)
     OR NOT EXISTS (SELECT 1 FROM public.commons_schema_migrations WHERE version=8) THEN
    RAISE EXCEPTION 'release schema receipt missing';
  END IF;
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
END;
$readiness$;
REVOKE ALL ON FUNCTION public.dice_release_readiness() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dice_release_readiness() TO service_role;
