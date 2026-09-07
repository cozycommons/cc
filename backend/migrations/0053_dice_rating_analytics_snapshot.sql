-- One SQL statement gives reports and progress APIs a coherent MVCC view.
-- Only already-public rating/game fields are included; RLS remains in force.
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
        'elo_rating', p.elo_rating, 'ranked_games_played', p.ranked_games_played,
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
        'team', gp.team, 'elo_before', gp.elo_before, 'elo_after', gp.elo_after
      ) order by gp.game_id, gp.user_id, gp.id)
      from public.dice_game_players gp
      join public.dice_games g on g.id = gp.game_id
      where g.live_result_state is null or g.live_result_state = 'official'
    ), '[]'::jsonb)
  )
$$;

revoke all on function public.dice_rating_analytics_snapshot() from public;
grant execute on function public.dice_rating_analytics_snapshot() to anon, authenticated, service_role;
