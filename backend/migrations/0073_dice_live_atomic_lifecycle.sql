drop function if exists public.dice_live_create_match(
  uuid, jsonb, jsonb, jsonb, jsonb, jsonb, boolean
);

create or replace function public.dice_live_create_match(
  p_match_id uuid,
  p_created_by uuid,
  p_team_order jsonb,
  p_teams jsonb,
  p_rules_snapshot jsonb,
  p_rating_snapshot jsonb,
  p_prediction_snapshot jsonb,
  p_ranked boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
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
$$;

revoke all on function public.dice_live_create_match(
  uuid, uuid, jsonb, jsonb, jsonb, jsonb, jsonb, boolean
) from public, anon, authenticated;
grant execute on function public.dice_live_create_match(
  uuid, uuid, jsonb, jsonb, jsonb, jsonb, jsonb, boolean
) to service_role;

-- Recheck lifecycle state after taking the same canonical lock used by result
-- deletion. An HTTP preflight can become stale while waiting for that lock.
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
$$;

revoke all on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) from public, anon, authenticated;
grant execute on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) to service_role;

create or replace function public.dice_live_delete_with_rating_mutation(
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
  p_request_fingerprint text,
  p_match_id uuid,
  p_deleted_by uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
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
$$;

revoke all on function public.dice_live_delete_with_rating_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb,
  text, text, text, text, uuid, uuid
) from public, anon, authenticated;
grant execute on function public.dice_live_delete_with_rating_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb,
  text, text, text, text, uuid, uuid
) to service_role;
