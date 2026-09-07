-- Atomically activate one verified canonical generation, then require that
-- activation before runtime mutations can enter the transaction body.

create table if not exists public.dice_rating_control (
  singleton boolean primary key default true check (singleton),
  canonical_active boolean not null default false,
  activated_at timestamptz,
  source_digest text,
  output_digest text,
  source_generation jsonb,
  state_generation jsonb
);
alter table public.dice_rating_control
  add column if not exists source_generation jsonb,
  add column if not exists state_generation jsonb;
alter table public.dice_rating_control enable row level security;
revoke all on table public.dice_rating_control from public, anon, authenticated, service_role;
grant select on table public.dice_rating_control to service_role;
insert into public.dice_rating_control (singleton, canonical_active)
values (true, false)
on conflict (singleton) do nothing;

create table if not exists public.dice_rating_mutation_receipts (
  mutation_id uuid primary key,
  operation text not null check (operation in ('create', 'update', 'delete')),
  game_id uuid not null,
  actor_id text,
  request_fingerprint text,
  source_digest text not null,
  output_digest text not null,
  players_updated integer not null,
  profiles_updated integer not null,
  created_at timestamptz not null default now()
);
alter table public.dice_rating_mutation_receipts
  add column if not exists actor_id text,
  add column if not exists request_fingerprint text,
  add column if not exists source_digest text,
  add column if not exists output_digest text,
  add column if not exists players_updated integer,
  add column if not exists profiles_updated integer,
  drop column if exists source_generation,
  drop column if exists state_generation;
alter table public.dice_rating_mutation_receipts
  alter column source_digest set not null,
  alter column output_digest set not null,
  alter column players_updated set not null,
  alter column profiles_updated set not null;
alter table public.dice_rating_mutation_receipts enable row level security;
revoke all on table public.dice_rating_mutation_receipts
  from public, anon, authenticated, service_role;
grant select on table public.dice_rating_mutation_receipts to service_role;

do $$
begin
  if to_regprocedure(
    'public.dice_rating_apply_game_mutation_unchecked(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb)'
  ) is null then
    alter function public.dice_rating_apply_game_mutation(
      jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
    ) rename to dice_rating_apply_game_mutation_unchecked;
  end if;
end
$$;

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

  -- dice_rating_commit owns the canonical advisory/table locks. They remain
  -- held through this outer transaction and bind the receipt to its exact state.
  committed := public.dice_rating_commit(
    p_source, p_player_snapshots, p_profile_states
  );
  control_state := jsonb_build_object(
    'canonical_active', true,
    'source_digest', p_source_digest,
    'output_digest', p_output_digest
  );
  insert into public.dice_rating_control (
    singleton, canonical_active, activated_at, source_digest, output_digest,
    source_generation, state_generation
  ) values (
    true, true, now(), p_source_digest, p_output_digest,
    p_source, committed->'state'
  )
  on conflict (singleton) do update set
    canonical_active = excluded.canonical_active,
    activated_at = excluded.activated_at,
    source_digest = excluded.source_digest,
    output_digest = excluded.output_digest,
    source_generation = excluded.source_generation,
    state_generation = excluded.state_generation;
  return committed || jsonb_build_object('control', control_state);
end;
$$;

create or replace function public.dice_rating_control_snapshot()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  control_state jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  select jsonb_build_object(
    'canonical_active', c.canonical_active,
    'source_digest', c.source_digest,
    'output_digest', c.output_digest,
    'source_generation', c.source_generation,
    'state_generation', c.state_generation
  ) into control_state
  from public.dice_rating_control c where c.singleton;
  return jsonb_build_object(
    'control', control_state,
    'source', public.dice_rating_source_snapshot(),
    'state', public.dice_rating_state_snapshot()
  );
end;
$$;

create or replace function public.dice_rating_mutation_receipt(p_mutation_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  receipt jsonb;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_rating.service_role_required';
  end if;
  select jsonb_build_object(
    'mutation_id', r.mutation_id,
    'operation', r.operation,
    'game_id', r.game_id,
    'actor_id', r.actor_id,
    'request_fingerprint', r.request_fingerprint,
    'source_digest', r.source_digest,
    'output_digest', r.output_digest,
    'players_updated', r.players_updated,
    'profiles_updated', r.profiles_updated
  ) into receipt
  from public.dice_rating_mutation_receipts r
  where r.mutation_id = p_mutation_id;
  return receipt;
end;
$$;

drop function if exists public.dice_rating_apply_game_mutation(
  jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
);
drop function if exists public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
);
drop function if exists public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text
);

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

  -- Serialize callers sharing a mutation ID before inspecting its receipt.
  -- A simultaneous retry therefore observes the first committed receipt
  -- instead of calculating a second mutation from stale source state.
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
    source_digest, output_digest,
    players_updated, profiles_updated
  ) values (
    p_mutation_id, p_operation, (p_game->>'id')::uuid,
    p_actor_id, p_request_fingerprint,
    p_source_digest, p_output_digest,
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

drop function if exists public.dice_rating_activate(jsonb, text, text);
revoke all on function public.dice_rating_commit_and_activate(
  jsonb, jsonb, jsonb, text, text
) from public, anon, authenticated;
revoke all on function public.dice_rating_control_snapshot() from public, anon, authenticated;
revoke all on function public.dice_rating_mutation_receipt(uuid) from public, anon, authenticated;
revoke all on function public.dice_rating_apply_game_mutation_unchecked(
  jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb
) from public, anon, authenticated, service_role;
revoke all on function public.dice_rating_commit(
  jsonb, jsonb, jsonb
) from service_role;
revoke all on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.dice_rating_commit_and_activate(
  jsonb, jsonb, jsonb, text, text
) to service_role;
grant execute on function public.dice_rating_control_snapshot() to service_role;
grant execute on function public.dice_rating_mutation_receipt(uuid) to service_role;
grant execute on function public.dice_rating_apply_game_mutation(
  uuid, jsonb, text, jsonb, jsonb, jsonb, jsonb, jsonb, text, text, text, text
) to service_role;
