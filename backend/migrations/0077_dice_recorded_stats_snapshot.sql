-- Persist the projector output on the official game. This is the only stats
-- snapshot read by game lists, game detail, postgame, and aggregate analytics.

alter table public.dice_games
  add column if not exists recorded_stats jsonb;

select pg_catalog.set_config('dice.live_materialization', 'on', false);

update public.dice_games game
set recorded_stats = jsonb_build_object(
  'schema_version', 'dice-recorded-stats/v1',
  'coverage', coalesce(live.projection->>'coverage', 'unknown'),
  'observations', coalesce((live.projection->>'observations')::integer, 0),
  'outcomes', coalesce(live.projection->'stats', '{}'::jsonb),
  'players', coalesce(live.projection->'player_stats', '{}'::jsonb)
)
from public.dice_live_matches live
where game.source_live_match_id = live.id
  and live.projection is not null;

select pg_catalog.set_config('dice.live_materialization', 'off', false);

create or replace function public.dice_live_materialize_result(
  p_match_id uuid, p_projection jsonb, p_status text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
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
$$;

revoke all on function public.dice_live_materialize_result(uuid, jsonb, text)
  from public, anon, authenticated;
