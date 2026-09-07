-- Apply a manual game mutation and its complete canonical rating replay in one
-- transaction. The backend prepares a pinned post-mutation generation; this
-- function owns the authoritative source rechecks and persistence boundary.

create or replace function public.dice_rating_apply_game_mutation(
  p_source jsonb,
  p_operation text,
  p_game jsonb,
  p_players jsonb,
  p_expected_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
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
  lock table public.dice_games, public.dice_game_players, public.dice_profiles,
    public.dice_elo_v11_refresh_status in share row exclusive mode;

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
$$;

revoke all on function public.dice_rating_apply_game_mutation(
  jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.dice_rating_apply_game_mutation(
  jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
) to service_role;
