-- Detect source writes that bypass the canonical mutation transaction and
-- clear the durable dirty marker only after an exact generation is committed.

alter table public.dice_rating_control
  add column if not exists dirty boolean not null default true,
  add column if not exists changed_at timestamptz,
  add column if not exists cleaned_at timestamptz,
  add column if not exists clean_source_digest text,
  add column if not exists clean_output_digest text;

create or replace function public.dice_rating_mark_dirty()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.dice_rating_control
  set dirty = true, changed_at = now()
  where singleton;
  if not found then
    raise exception using errcode = 'P0001', message = 'dice_rating.control_missing';
  end if;
  return null;
end;
$$;

drop trigger if exists dice_rating_dirty_games on public.dice_games;
create trigger dice_rating_dirty_games
after insert or delete or update of
  id, ranked, team1_score, team2_score, winner_team, played_at, created_at,
  tournament_id, source_live_match_id, live_result_state, termination_reason,
  detail_coverage, stats_complete
on public.dice_games
for each statement execute function public.dice_rating_mark_dirty();

drop trigger if exists dice_rating_dirty_players on public.dice_game_players;
create trigger dice_rating_dirty_players
after insert or delete or update of
  id, game_id, user_id, team, counts_for_group_stage, self_sinks, sinks,
  elo_before, elo_after, rating_deviation_before, rating_deviation_after
on public.dice_game_players
for each statement execute function public.dice_rating_mark_dirty();

drop trigger if exists dice_rating_dirty_profiles on public.dice_profiles;
create trigger dice_rating_dirty_profiles
after insert or delete or update of
  user_id, elo_rating, rating_deviation, elo_model_version,
  ranked_games_played, games_played, wins, losses, ranked_wins, ranked_losses,
  normal_wins, normal_losses, self_sinks, sinks
on public.dice_profiles
for each statement execute function public.dice_rating_mark_dirty();

-- Preserve a clean, already-activated production generation during rollout.
-- If source or state moved since activation, fail closed as dirty instead.
update public.dice_rating_control c
set dirty = not (
      c.canonical_active
      and c.source_generation is not distinct from public.dice_rating_source_snapshot()
      and c.state_generation is not distinct from public.dice_rating_state_snapshot()
    ),
    changed_at = case
      when c.canonical_active
       and c.source_generation is not distinct from public.dice_rating_source_snapshot()
       and c.state_generation is not distinct from public.dice_rating_state_snapshot()
      then c.changed_at else coalesce(c.changed_at, now()) end,
    cleaned_at = case
      when c.canonical_active
       and c.source_generation is not distinct from public.dice_rating_source_snapshot()
       and c.state_generation is not distinct from public.dice_rating_state_snapshot()
      then coalesce(c.cleaned_at, c.activated_at, now()) else c.cleaned_at end,
    clean_source_digest = case
      when c.canonical_active
       and c.source_generation is not distinct from public.dice_rating_source_snapshot()
       and c.state_generation is not distinct from public.dice_rating_state_snapshot()
      then c.source_digest else c.clean_source_digest end,
    clean_output_digest = case
      when c.canonical_active
       and c.source_generation is not distinct from public.dice_rating_source_snapshot()
       and c.state_generation is not distinct from public.dice_rating_state_snapshot()
      then c.output_digest else c.clean_output_digest end
where c.singleton;

revoke all on function public.dice_rating_mark_dirty()
  from public, anon, authenticated, service_role;
revoke all on function public.dice_rating_commit(jsonb, jsonb, jsonb)
  from service_role;

-- The live reopen path historically touched profiles before games, opposite
-- the canonical commit lock order. Take the canonical advisory lock before
-- entering either materialization path so refresh and live commands serialize.
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

create or replace function public.dice_rating_commit_and_activate(
  p_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb,
  p_source_digest text,
  p_output_digest text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  committed jsonb;
  control_state jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  if p_source_digest is null
     or p_output_digest is null
     or p_source_digest !~ '^[0-9a-f]{64}$'
     or p_output_digest !~ '^[0-9a-f]{64}$' then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_activation';
  end if;

  committed := public.dice_rating_commit(
    p_source, p_player_snapshots, p_profile_states
  );
  control_state := jsonb_build_object(
    'canonical_active', true,
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
  insert into public.dice_rating_control (
    singleton, canonical_active, activated_at, dirty, cleaned_at,
    source_digest, output_digest, clean_source_digest, clean_output_digest,
    source_generation, state_generation
  ) values (
    true, true, now(), false, now(),
    p_source_digest, p_output_digest, p_source_digest, p_output_digest,
    p_source, committed->'state'
  )
  on conflict (singleton) do update set
    canonical_active = excluded.canonical_active,
    activated_at = excluded.activated_at,
    dirty = excluded.dirty,
    cleaned_at = excluded.cleaned_at,
    source_digest = excluded.source_digest,
    output_digest = excluded.output_digest,
    clean_source_digest = excluded.clean_source_digest,
    clean_output_digest = excluded.clean_output_digest,
    source_generation = excluded.source_generation,
    state_generation = excluded.state_generation;
  return committed || jsonb_build_object('control', control_state);
end;
$$;

create or replace function public.dice_rating_status()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  status jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  select jsonb_build_object(
    'canonical_active', c.canonical_active,
    'dirty', c.dirty,
    'changed_at', c.changed_at,
    'cleaned_at', c.cleaned_at,
    'clean_source_digest', c.clean_source_digest,
    'clean_output_digest', c.clean_output_digest
  ) into status
  from public.dice_rating_control c where c.singleton;
  return status;
end;
$$;

create or replace function public.dice_rating_refresh_if_active(
  p_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb,
  p_source_digest text,
  p_output_digest text
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
  if not exists (
    select 1 from public.dice_rating_control where singleton and canonical_active
  ) then
    raise exception using errcode = '55000', message = 'dice_rating.cutover_required';
  end if;
  if p_source_digest is null
     or p_output_digest is null
     or p_source_digest !~ '^[0-9a-f]{64}$'
     or p_output_digest !~ '^[0-9a-f]{64}$' then
    raise exception using errcode = '22023', message = 'dice_rating.invalid_refresh_digest';
  end if;
  committed := public.dice_rating_commit(
    p_source, p_player_snapshots, p_profile_states
  );
  update public.dice_rating_control set
    dirty = false,
    cleaned_at = now(),
    clean_source_digest = p_source_digest,
    clean_output_digest = p_output_digest
  where singleton;
  if not found then
    raise exception using errcode = 'P0001', message = 'dice_rating.control_missing';
  end if;
  return committed || jsonb_build_object(
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
end;
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
  if not exists (
    select 1 from public.dice_rating_control
    where singleton and canonical_active
  ) then
    raise exception using errcode = '55000', message = 'dice_rating.cutover_required';
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
  update public.dice_rating_control
  set dirty = false,
      cleaned_at = now(),
      clean_source_digest = p_source_digest,
      clean_output_digest = p_output_digest
  where singleton;
  if not found then
    raise exception using errcode = 'P0001', message = 'dice_rating.control_missing';
  end if;
  return committed || jsonb_build_object(
    'mutation_id', p_mutation_id,
    'actor_id', p_actor_id,
    'request_fingerprint', p_request_fingerprint,
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
end;
$$;

revoke all on function public.dice_rating_commit_and_activate(
  jsonb, jsonb, jsonb, text, text
) from public, anon, authenticated;
revoke all on function public.dice_rating_status()
  from public, anon, authenticated;
revoke all on function public.dice_rating_refresh_if_active(
  jsonb, jsonb, jsonb, text, text
) from public, anon, authenticated;
revoke all on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.dice_rating_commit_and_activate(
  jsonb, jsonb, jsonb, text, text
) to service_role;
grant execute on function public.dice_rating_status() to service_role;
grant execute on function public.dice_rating_refresh_if_active(
  jsonb, jsonb, jsonb, text, text
) to service_role;
grant execute on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) to service_role;
