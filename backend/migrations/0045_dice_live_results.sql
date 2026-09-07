-- Dice live v1 official-result materialization.  This is derived state over
-- the immutable live ledger; reopening never deletes or edits an event.

alter table public.dice_games
  add column if not exists source_live_match_id uuid,
  add column if not exists live_result_state text,
  add column if not exists termination_reason text,
  add column if not exists detail_coverage text not null default 'complete',
  add column if not exists stats_complete boolean not null default true;

alter table public.dice_games alter column winner_team drop not null;

create unique index if not exists dice_games_source_live_match_idx
  on public.dice_games (source_live_match_id)
  where source_live_match_id is not null;
alter table public.dice_games
  add constraint dice_games_live_result_state_check
  check (live_result_state in ('official', 'reopened'));
alter table public.dice_games
  add constraint dice_games_termination_reason_check
  check (termination_reason is null or termination_reason in
    ('target_reached', 'off_roof', 'forfeit', 'time_limit', 'mutual_end', 'other'));
alter table public.dice_games
  add constraint dice_games_detail_coverage_check
  check (detail_coverage in ('complete', 'partial', 'unknown'));

drop policy dice_games_public_read on public.dice_games;
create policy dice_games_public_read on public.dice_games
  for select to anon, authenticated
  using (live_result_state is null or live_result_state = 'official');

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
begin
  select * into m from public.dice_live_matches where id = p_match_id;
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
         source_live_match_id, live_result_state, termination_reason, detail_coverage, stats_complete)
      values (m.created_by, false, (p_projection->'score'->>0)::integer,
        (p_projection->'score'->>1)::integer, winner, now(), m.id, 'official',
        p_projection->>'termination_reason', p_projection->>'coverage',
        (p_projection->>'coverage') = 'complete') returning id into result_id;
      update public.dice_live_matches set official_result_id = result_id where id = m.id;
      delta := 1;
    else
      select live_result_state into team from public.dice_games where id = result_id;
      update public.dice_games set team1_score = (p_projection->'score'->>0)::integer,
        team2_score = (p_projection->'score'->>1)::integer, winner_team = winner,
        live_result_state = 'official', termination_reason = p_projection->>'termination_reason',
        detail_coverage = p_projection->>'coverage', stats_complete = (p_projection->>'coverage') = 'complete'
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

alter function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) rename to dice_live_append_command_v1;

create or replace function public.dice_live_append_command(
  p_match_id uuid, p_recorded_by uuid, p_client_command_id text,
  p_expected_version integer, p_canonical_payload jsonb, p_events jsonb,
  p_projection jsonb, p_score smallint[], p_status text, p_detail_coverage text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_receipt jsonb;
  official jsonb;
  already_exists boolean;
begin
  select true into already_exists from public.dice_live_commands
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  v_receipt := public.dice_live_append_command_v1(
    p_match_id, p_recorded_by, p_client_command_id, p_expected_version,
    p_canonical_payload, p_events, p_projection, p_score, p_status, p_detail_coverage);
  if already_exists then return v_receipt; end if;
  official := public.dice_live_materialize_result(p_match_id, p_projection, p_status);
  v_receipt := jsonb_set(v_receipt, '{official_result}', coalesce(official, 'null'::jsonb), true);
  update public.dice_live_commands set receipt = v_receipt
   where match_id = p_match_id and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  return v_receipt;
end;
$$;

revoke all on function public.dice_live_materialize_result(uuid, jsonb, text) from public, anon, authenticated;
revoke all on function public.dice_live_append_command(uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text) from public, anon, authenticated;
grant execute on function public.dice_live_append_command(uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text) to service_role;
