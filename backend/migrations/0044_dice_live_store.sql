-- Dice live referee v1: private append-only match store.
-- Gameplay rows are written only by the backend service role.  The JSON
-- snapshots and projection are materializations; dice_live_events is the
-- durable source consumed by the projector.

create table public.dice_live_matches (
  id uuid primary key default gen_random_uuid(),
  created_by uuid not null references public.dice_profiles(user_id),
  team_order jsonb not null,
  teams jsonb not null,
  rules_snapshot jsonb not null,
  version integer not null default 0,
  status text not null default 'active',
  score smallint[] not null default array[0, 0]::smallint[],
  detail_coverage text not null default 'unknown',
  projection jsonb not null default '{"score":[0,0],"status":"active","coverage":"unknown","observations":0,"stats":{}}'::jsonb,
  official_result_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint dice_live_matches_team_order_check check (
    jsonb_typeof(team_order) = 'array' and jsonb_array_length(team_order) = 2
  ),
  constraint dice_live_matches_teams_check check (jsonb_typeof(teams) = 'object'),
  constraint dice_live_matches_status_check check (
    status in ('active', 'awaiting_replay', 'ready_to_finish', 'completed')
  ),
  constraint dice_live_matches_coverage_check check (
    detail_coverage in ('complete', 'partial', 'unknown')
  ),
  constraint dice_live_matches_score_check check (
    cardinality(score) = 2 and score[1] >= 0 and score[2] >= 0
  )
);

create index dice_live_matches_ongoing_idx
  on public.dice_live_matches (status, updated_at desc)
  where status <> 'completed';

create table public.dice_live_referees (
  match_id uuid not null references public.dice_live_matches(id) on delete cascade,
  user_id uuid not null references public.dice_profiles(user_id) on delete cascade,
  joined_at timestamptz not null default now(),
  left_at timestamptz,
  primary key (match_id, user_id)
);

create index dice_live_referees_current_idx
  on public.dice_live_referees (user_id, match_id)
  where left_at is null;

create table public.dice_live_commands (
  id uuid primary key default gen_random_uuid(),
  match_id uuid not null references public.dice_live_matches(id) on delete cascade,
  recorded_by uuid not null references public.dice_profiles(user_id),
  client_command_id text not null,
  canonical_payload jsonb not null,
  expected_version integer not null,
  accepted_version integer not null,
  first_sequence integer not null,
  last_sequence integer not null,
  receipt jsonb not null,
  created_at timestamptz not null default now(),
  unique (match_id, recorded_by, client_command_id),
  constraint dice_live_commands_version_check check (
    expected_version >= 0 and accepted_version > expected_version
  ),
  constraint dice_live_commands_sequence_check check (
    first_sequence > 0 and last_sequence >= first_sequence
  )
);

create index dice_live_commands_match_idx
  on public.dice_live_commands (match_id, accepted_version);

create table public.dice_live_events (
  id text primary key,
  match_id uuid not null references public.dice_live_matches(id) on delete cascade,
  match_version integer not null,
  sequence integer not null,
  client_command_id text not null,
  command_index integer not null,
  recorded_by uuid not null references public.dice_profiles(user_id),
  recorded_at timestamptz not null default now(),
  match_elapsed_ms integer not null default 0,
  kind text not null,
  event jsonb not null,
  unique (match_id, sequence),
  unique (match_id, match_version, command_index),
  constraint dice_live_events_version_check check (match_version > 0),
  constraint dice_live_events_sequence_check check (sequence > 0),
  constraint dice_live_events_command_index_check check (command_index >= 0),
  constraint dice_live_events_elapsed_check check (match_elapsed_ms >= 0),
  constraint dice_live_events_kind_check check (
    kind in ('observation', 'correction', 'retoss_decision', 'off_roof',
             'score_checkpoint', 'completion')
  )
);

create index dice_live_events_match_sequence_idx
  on public.dice_live_events (match_id, sequence);

alter table public.dice_live_matches enable row level security;
alter table public.dice_live_referees enable row level security;
alter table public.dice_live_commands enable row level security;
alter table public.dice_live_events enable row level security;

revoke all on table public.dice_live_matches, public.dice_live_referees,
  public.dice_live_commands, public.dice_live_events from public, anon, authenticated;
grant all on table public.dice_live_matches, public.dice_live_referees,
  public.dice_live_commands, public.dice_live_events to service_role;

create or replace function public.dice_live_events_immutable()
returns trigger
language plpgsql
as $$
begin
  raise exception using
    errcode = '55000',
    message = 'dice_live.events_append_only',
    detail = 'live event rows may only be inserted by the append command';
end;
$$;

create trigger dice_live_events_no_update
before update or delete on public.dice_live_events
for each row execute function public.dice_live_events_immutable();

create or replace function public.dice_live_append_command(
  p_match_id uuid,
  p_recorded_by uuid,
  p_client_command_id text,
  p_expected_version integer,
  p_canonical_payload jsonb,
  p_events jsonb,
  p_projection jsonb,
  p_score smallint[],
  p_status text,
  p_detail_coverage text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_match public.dice_live_matches%rowtype;
  v_command public.dice_live_commands%rowtype;
  v_new_version integer;
  v_first_sequence integer;
  v_event jsonb;
  v_sequence integer;
  v_command_index integer;
  v_receipt jsonb;
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_live.service_role_required';
  end if;
  if jsonb_typeof(p_events) <> 'array' or jsonb_array_length(p_events) not between 1 and 2 then
    raise exception using errcode = '22023', message = 'dice_live.invalid_command';
  end if;
  if cardinality(p_score) <> 2 or p_status not in ('active', 'awaiting_replay', 'ready_to_finish', 'completed')
     or p_detail_coverage not in ('complete', 'partial', 'unknown') then
    raise exception using errcode = '22023', message = 'dice_live.invalid_projection';
  end if;

  -- The identity check deliberately precedes the version check.  An exact
  -- timeout retry remains idempotent even after another command advanced N.
  select * into v_command
    from public.dice_live_commands
   where match_id = p_match_id
     and recorded_by = p_recorded_by
     and client_command_id = p_client_command_id;
  if found then
    if v_command.canonical_payload = p_canonical_payload then
      return v_command.receipt;
    end if;
    raise exception using
      errcode = 'P0001', message = 'dice_live.command_id_conflict',
      detail = jsonb_build_object('match_id', p_match_id, 'client_command_id', p_client_command_id)::text;
  end if;

  select * into v_match from public.dice_live_matches where id = p_match_id for update;
  if not found then
    raise exception using errcode = 'P0001', message = 'dice_live.match_not_found';
  end if;
  if not exists (
    select 1 from public.dice_live_referees
     where match_id = p_match_id and user_id = p_recorded_by and left_at is null
  ) then
    raise exception using errcode = '42501', message = 'dice_live.referee_not_joined';
  end if;
  if v_match.version <> p_expected_version then
    raise exception using
      errcode = 'P0001', message = 'dice_live.stale_version',
      detail = jsonb_build_object(
        'current_version', v_match.version,
        'projection', v_match.projection
      )::text;
  end if;

  v_new_version := v_match.version + 1;
  select coalesce(max(sequence), 0) + 1 into v_first_sequence
    from public.dice_live_events where match_id = p_match_id;
  for v_event, v_command_index in
    select value, ordinality::integer - 1
      from jsonb_array_elements(p_events) with ordinality
  loop
    v_sequence := v_first_sequence + v_command_index;
    v_event := jsonb_set(v_event, '{match_id}', to_jsonb(p_match_id::text), true);
    v_event := jsonb_set(v_event, '{match_version}', to_jsonb(v_new_version), true);
    v_event := jsonb_set(v_event, '{sequence}', to_jsonb(v_sequence), true);
    v_event := jsonb_set(v_event, '{client_command_id}', to_jsonb(p_client_command_id), true);
    v_event := jsonb_set(v_event, '{command_index}', to_jsonb(v_command_index), true);
    v_event := jsonb_set(v_event, '{recorded_by}', to_jsonb(p_recorded_by::text), true);
    v_event := jsonb_set(v_event, '{recorded_at}', to_jsonb(now()), true);
    insert into public.dice_live_events (
      id, match_id, match_version, sequence, client_command_id, command_index,
      recorded_by, recorded_at, match_elapsed_ms, kind, event
    ) values (
      v_event->>'id', p_match_id, v_new_version, v_sequence,
      p_client_command_id, v_command_index, p_recorded_by,
      coalesce((v_event->>'recorded_at')::timestamptz, now()),
      coalesce((v_event->>'match_elapsed_ms')::integer, 0),
      v_event->>'kind', v_event
    );
  end loop;

  v_receipt := jsonb_build_object(
    'accepted_version', v_new_version,
    'first_sequence', v_first_sequence,
    'last_sequence', v_first_sequence + jsonb_array_length(p_events) - 1,
    'projection', p_projection,
    'official_result', null
  );
  insert into public.dice_live_commands (
    match_id, recorded_by, client_command_id, canonical_payload,
    expected_version, accepted_version, first_sequence, last_sequence, receipt
  ) values (
    p_match_id, p_recorded_by, p_client_command_id, p_canonical_payload,
    p_expected_version, v_new_version, v_first_sequence,
    v_first_sequence + jsonb_array_length(p_events) - 1, v_receipt
  );
  update public.dice_live_matches
     set version = v_new_version,
         status = p_status,
         score = p_score,
         detail_coverage = p_detail_coverage,
         projection = p_projection,
         updated_at = now()
   where id = p_match_id;
  return v_receipt;
end;
$$;

revoke all on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) from public, anon, authenticated;
grant execute on function public.dice_live_append_command(
  uuid, uuid, text, integer, jsonb, jsonb, jsonb, smallint[], text, text
) to service_role;
