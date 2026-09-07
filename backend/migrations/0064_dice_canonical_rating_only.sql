-- Retire the completed rating cutover control plane. Canonical rating state is
-- now maintained only by the atomic manual-game mutation RPC. Live results
-- remain unranked and update their ordinary aggregates in their own transaction.

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('dice:elo:canonical', 0)
);

do $$
declare
  canonical_ready boolean;
begin
  if exists (select 1 from public.dice_profiles)
     and to_regclass('public.dice_rating_control') is null
     and not exists (
       select 1 from pg_catalog.pg_constraint
       where conrelid = 'public.dice_games'::regclass
         and conname = 'dice_games_live_results_unranked'
     ) then
    raise exception using
      errcode = '55000',
      message = 'dice_rating.canonical_control_required';
  elsif to_regclass('public.dice_rating_control') is not null
     and exists (select 1 from public.dice_profiles) then
    execute 'select exists (
      select 1 from public.dice_rating_control
      where singleton and canonical_active and not dirty
    )' into canonical_ready;
    if not canonical_ready then
      raise exception using
        errcode = '55000',
        message = 'dice_rating.clean_canonical_state_required';
    end if;
  end if;
end
$$;

drop trigger if exists dice_rating_dirty_games on public.dice_games;
drop trigger if exists dice_rating_dirty_players on public.dice_game_players;
drop trigger if exists dice_rating_dirty_profiles on public.dice_profiles;

do $$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.dice_games'::regclass
      and conname = 'dice_games_live_results_unranked'
  ) then
    alter table public.dice_games
      add constraint dice_games_live_results_unranked
      check (source_live_match_id is null or not ranked);
  end if;
end
$$;

create or replace function public.dice_live_result_write_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if old.source_live_match_id is not null
     and current_setting('dice.live_materialization', true) is distinct from 'on' then
    raise exception using errcode = '55000', message = 'dice_live.result_managed_by_live_match';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

drop trigger if exists dice_live_result_write_guard on public.dice_games;
create trigger dice_live_result_write_guard
before update or delete on public.dice_games
for each row execute function public.dice_live_result_write_guard();

create or replace function public.dice_live_append_command(
  p_match_id uuid, p_recorded_by uuid, p_client_command_id text,
  p_expected_version integer, p_canonical_payload jsonb, p_events jsonb,
  p_projection jsonb, p_score smallint[], p_status text, p_detail_coverage text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
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
$$;

create or replace function public.dice_rating_analytics_snapshot()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select jsonb_build_object(
    'snapshot_version', 'dice-rating-analytics/v1',
    'profiles', coalesce((
      select jsonb_agg(jsonb_build_object(
        'user_id', p.user_id, 'display_name', p.display_name,
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
        'id', g.id, 'ranked', g.ranked, 'winner_team', g.winner_team,
        'team1_score', g.team1_score, 'team2_score', g.team2_score,
        'played_at', g.played_at, 'created_at', g.created_at,
        'live_result_state', g.live_result_state
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
$$;

create or replace function public.dice_rating_apply_game_mutation(
  p_mutation_id uuid,
  p_source jsonb,
  p_operation text,
  p_game jsonb,
  p_players jsonb,
  p_expected_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb,
  p_source_digest text,
  p_output_digest text,
  p_actor_id text,
  p_request_fingerprint text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
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
$$;

drop function if exists public.dice_rating_refresh_if_active(jsonb, jsonb, jsonb, text, text);
drop function if exists public.dice_rating_status();
drop function if exists public.dice_rating_commit_and_activate(jsonb, jsonb, jsonb, text, text);
drop function if exists public.dice_rating_control_snapshot();
drop function if exists public.dice_rating_generation_snapshot();
drop function if exists public.dice_rating_mark_dirty();
drop table if exists public.dice_rating_control;

revoke all on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) from public, anon, authenticated;
grant execute on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) to service_role;
revoke all on function public.dice_live_result_write_guard()
  from public, anon, authenticated, service_role;
revoke all on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) from public, anon, authenticated;
revoke all on function public.dice_rating_apply_game_mutation_unchecked(
  jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
) from public, anon, authenticated, service_role;
revoke all on function public.dice_rating_commit(jsonb, jsonb, jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) to service_role;

comment on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) is 'Atomic canonical game and rating mutation with idempotency receipt.';
comment on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) is 'Atomic live command materialization. Live results are unranked; ranked live support must use the canonical rating mutation transaction.';
