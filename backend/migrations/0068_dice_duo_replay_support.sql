-- Duo ratings are derived by deterministic chronological replay. Keep the
-- source tables authoritative and make the replay query cheap without adding
-- a mutable/cached duo state table.

alter table public.dice_games
  add column if not exists duo_only boolean not null default false;
comment on column public.dice_games.duo_only is
  'Ranked history used by duo replay but intentionally excluded from individual Elo replay.';

create index if not exists dice_games_duo_replay_idx
  on public.dice_games (played_at asc, created_at asc, id asc);

create index if not exists dice_game_players_duo_replay_idx
  on public.dice_game_players (game_id, team asc, user_id asc);

comment on index public.dice_games_duo_replay_idx is
  'Supports deterministic replay of completed ranked 2v2 duo history.';

comment on index public.dice_game_players_duo_replay_idx is
  'Supports ordered team membership reads for duo replay.';

-- Duo history is served only by the feature-gated backend API. Keep the
-- established public game feed and direct PostgREST reads individual-only;
-- the service-role replay RPC is the sole database path that includes duo
-- evidence.
drop policy if exists dice_games_public_read on public.dice_games;
create policy dice_games_public_read on public.dice_games
  for select to anon, authenticated
  using (
    (live_result_state is null or live_result_state = 'official')
    and duo_only is not true
  );

drop policy if exists dice_game_players_public_read on public.dice_game_players;
create policy dice_game_players_public_read on public.dice_game_players
  for select to anon, authenticated
  using (
    exists (
      select 1 from public.dice_games g
      where g.id = game_id and g.duo_only is not true
    )
  );

-- The canonical individual rating source deliberately excludes duo-only
-- history.  Keep that isolation at the database boundary so a subsequent
-- normal game mutation cannot accidentally replay seeded or production duo
-- matches into individual Elo/aggregates.
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
      join public.dice_games g on g.id = gp.game_id
      where g.duo_only is not true
    ), '[]'::jsonb)
  )
$$;

-- Duo cards use the same coherent analytics snapshot as player ratings. Add
-- the already-public avatar field here so replay consumers can render the
-- established Dice identity without a second, inconsistent profile read.
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
        'id', g.id, 'ranked', g.ranked, 'duo_only', g.duo_only, 'winner_team', g.winner_team,
        'team1_score', g.team1_score, 'team2_score', g.team2_score,
        'played_at', g.played_at, 'created_at', g.created_at,
        'live_result_state', g.live_result_state
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
$$;

-- Keep duo requests bounded as history grows. Below the cap this delegates to
-- the canonical coherent snapshot; above it the API fails closed instead of
-- transferring an unbounded replay payload or silently truncating history.
create or replace function public.dice_duo_replay_snapshot(p_max_games integer default 5000)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
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
$$;

revoke all on function public.dice_duo_replay_snapshot(integer) from public;
grant execute on function public.dice_duo_replay_snapshot(integer) to service_role;
