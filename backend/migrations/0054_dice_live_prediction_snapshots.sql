-- Prediction inputs are captured independently from social Elo so live odds
-- remain reproducible even when rating formulas or profile totals change.
alter table public.dice_live_matches
  add column if not exists prediction_snapshot jsonb;

-- Extend the existing one-statement analytics snapshot with the one additional
-- pregame aggregate needed by the independent model. Replacing the function
-- preserves its grants and keeps report/progress callers backward compatible.
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
        'ranked_wins', p.ranked_wins,
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

alter table public.dice_live_matches
  drop constraint if exists dice_live_matches_prediction_snapshot_check;

alter table public.dice_live_matches
  add constraint dice_live_matches_prediction_snapshot_check check (
        prediction_snapshot is null or (
          jsonb_typeof(prediction_snapshot) = 'object'
          and prediction_snapshot ?& array[
            'model_id', 'model_version', 'dataset_version', 'captured_at',
            'team1_prior_win_rate', 'team2_prior_win_rate', 'team1_probability'
          ]
          and jsonb_typeof(prediction_snapshot->'model_id') = 'string'
          and jsonb_typeof(prediction_snapshot->'model_version') = 'string'
          and jsonb_typeof(prediction_snapshot->'dataset_version') = 'string'
          and jsonb_typeof(prediction_snapshot->'captured_at') = 'string'
          and jsonb_typeof(prediction_snapshot->'team1_prior_win_rate') = 'number'
          and jsonb_typeof(prediction_snapshot->'team2_prior_win_rate') = 'number'
          and jsonb_typeof(prediction_snapshot->'team1_probability') = 'number'
          and (prediction_snapshot->>'team1_prior_win_rate')::numeric between 0 and 1
          and (prediction_snapshot->>'team2_prior_win_rate')::numeric between 0 and 1
          and (prediction_snapshot->>'team1_probability')::numeric between 0 and 1
        )
  );

create or replace function public.dice_live_prediction_snapshot_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.prediction_snapshot is distinct from new.prediction_snapshot then
    raise exception 'prediction_snapshot is immutable' using errcode = '22023';
  end if;
  return new;
end
$$;

drop trigger if exists dice_live_prediction_snapshot_immutable on public.dice_live_matches;
create trigger dice_live_prediction_snapshot_immutable
before update of prediction_snapshot on public.dice_live_matches
for each row execute function public.dice_live_prediction_snapshot_immutable();

comment on column public.dice_live_matches.prediction_snapshot is
  'Immutable versioned pregame model input and probability captured at match creation; null uses the neutral fallback.';
