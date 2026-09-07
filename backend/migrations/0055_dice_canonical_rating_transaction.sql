-- Canonical Elo transaction seam. This migration is additive: runtime writes
-- continue using the shadow path until the explicit cutover deploy.

create or replace function public.dice_rating_source_snapshot()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
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
      ) source
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(to_jsonb(source) order by source.game_id, source.user_id, source.id)
      from (
        select gp.id, gp.game_id, gp.user_id, gp.team,
          gp.counts_for_group_stage, gp.self_sinks, gp.sinks
        from public.dice_game_players gp
      ) source
    ), '[]'::jsonb)
  )
$$;

create or replace function public.dice_rating_state_snapshot()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
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
    ), '[]'::jsonb)
  )
$$;

create or replace function public.dice_rating_commit(
  p_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
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
$$;

revoke all on function public.dice_rating_source_snapshot() from public, anon, authenticated;
revoke all on function public.dice_rating_state_snapshot() from public, anon, authenticated;
revoke all on function public.dice_rating_commit(jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.dice_rating_source_snapshot() to service_role;
grant execute on function public.dice_rating_state_snapshot() to service_role;
grant execute on function public.dice_rating_commit(jsonb, jsonb, jsonb) to service_role;
