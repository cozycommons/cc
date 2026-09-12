-- Some long-lived environments applied an early 0068 draft before its
-- canonical snapshot exclusions were finalized. Reassert the immutable
-- boundary so duo-only ladder history can never enter individual Elo replay.

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
$$;

-- An early snapshot boundary could also write individual transitions onto
-- duo-only evidence. Those columns have no meaning for the separate ladder.
update public.dice_game_players player set
  elo_before = null,
  elo_after = null,
  rating_deviation_before = null,
  rating_deviation_after = null
from public.dice_games game
where game.id = player.game_id
  and game.duo_only;

-- The backend startup job supplies a deterministic plan for the corrected
-- source. The existing canonical commit owns locks, source comparison, shape
-- validation, and the all-profile/all-player transaction.
create or replace function public.dice_rating_commit_rebuild(
  p_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  return public.dice_rating_commit(p_source, p_player_snapshots, p_profile_states);
end;
$$;

revoke all on function public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)
  from public, anon, authenticated;
grant execute on function public.dice_rating_commit_rebuild(jsonb,jsonb,jsonb)
  to service_role;

-- Requeue ranked live results because an earlier replay may have acknowledged
-- its repair while using the stale source boundary. The normal bounded repair
-- path is idempotent and removes each row only after canonical commit.
insert into public.dice_live_rating_repairs (match_id)
select live.id
from public.dice_live_matches live
join public.dice_games game on game.id = live.official_result_id
where live.deleted_at is null
  and game.ranked
  and game.live_result_state in ('official', 'reopened')
on conflict (match_id) do update set
  attempts = 0,
  last_error = null,
  updated_at = now();
