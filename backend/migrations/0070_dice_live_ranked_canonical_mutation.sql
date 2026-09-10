-- Allow live results to participate in the canonical rating transaction.
-- The live ledger remains append-only; only its materialized projection may
-- carry the ranked flag, and only through the service-side mutation RPC.
alter table public.dice_games
  drop constraint if exists dice_games_live_results_unranked;

create or replace function public.dice_live_result_write_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if old.source_live_match_id is not null
     and current_setting('dice.live_materialization', true) is distinct from 'on'
     and current_setting('dice.rating_mutation', true) is distinct from 'on' then
    raise exception using errcode = '55000', message = 'dice_live.result_managed_by_live_match';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

comment on function public.dice_live_result_write_guard()
  is 'dice:live-ranked-canonical-mutation/v1';

drop trigger if exists dice_live_result_write_guard on public.dice_games;
create trigger dice_live_result_write_guard
before update or delete on public.dice_games
for each row execute function public.dice_live_result_write_guard();

-- Keep the canonical mutation atomic while allowing its guarded write to the
-- live projection. This function is executable only by service_role.
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

  perform pg_catalog.set_config('dice.rating_mutation', 'on', true);
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
  return committed || jsonb_build_object(
    'mutation_id', p_mutation_id,
    'actor_id', p_actor_id,
    'request_fingerprint', p_request_fingerprint,
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
end;
$$;

revoke all on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) to service_role;

comment on function public.dice_live_result_write_guard() is
  'Live projections may only be changed by live materialization or canonical rating mutation.';
