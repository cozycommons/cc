-- Elo v1.1 is additive. Keep the v1.0 rating and per-game snapshots as an
-- immutable audit trail while the new replay is shadowed and reviewed.
alter table public.dice_profiles
  add column if not exists elo_v11_rating int,
  add column if not exists rating_deviation numeric(6,2),
  add column if not exists elo_model_version text not null default '1.0.0';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_profiles'::regclass
      and conname = 'dice_profiles_rating_deviation_check'
  ) then
    alter table public.dice_profiles
      add constraint dice_profiles_rating_deviation_check
      check (rating_deviation is null or (rating_deviation >= 50 and rating_deviation <= 350));
  end if;
end
$$;

comment on column public.dice_profiles.elo_v11_rating is
  'Shadow Elo v1.1 rating; null until the deterministic backfill/replay populates it.';
comment on column public.dice_profiles.rating_deviation is
  'Shadow Elo v1.1 deviation immediately after the last ranked game; null means the profile has not been backfilled.';
comment on column public.dice_profiles.elo_model_version is
  'Canonical rating model for future writes; remains 1.0.0 until explicit cutover.';

create table if not exists public.dice_elo_v11_refresh_status (
  singleton boolean primary key default true check (singleton),
  dirty boolean not null default true,
  changed_at timestamptz not null default now(),
  promoted_at timestamptz,
  source_fingerprint text
);
alter table public.dice_elo_v11_refresh_status enable row level security;
revoke all on table public.dice_elo_v11_refresh_status from public, anon, authenticated;
grant select, insert, update on table public.dice_elo_v11_refresh_status to service_role;
insert into public.dice_elo_v11_refresh_status (singleton, dirty)
values (true, true)
on conflict (singleton) do nothing;

alter table public.dice_game_players
  add column if not exists elo_v11_before int,
  add column if not exists elo_v11_after int,
  add column if not exists rating_deviation_before numeric(6,2),
  add column if not exists rating_deviation_after numeric(6,2);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_game_players'::regclass
      and conname = 'dice_game_players_rating_deviation_before_check'
  ) then
    alter table public.dice_game_players
      add constraint dice_game_players_rating_deviation_before_check
      check (rating_deviation_before is null or (rating_deviation_before >= 50 and rating_deviation_before <= 350));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_game_players'::regclass
      and conname = 'dice_game_players_rating_deviation_after_check'
  ) then
    alter table public.dice_game_players
      add constraint dice_game_players_rating_deviation_after_check
      check (rating_deviation_after is null or (rating_deviation_after >= 50 and rating_deviation_after <= 350));
  end if;
end
$$;

comment on column public.dice_game_players.elo_v11_before is
  'Shadow Elo v1.1 rating before this ranked game; v1.0 elo_before is preserved.';
comment on column public.dice_game_players.elo_v11_after is
  'Shadow Elo v1.1 rating after this ranked game; v1.0 elo_after is preserved.';

create or replace function public.dice_elo_v11_mark_dirty()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.dice_elo_v11_refresh_status (singleton, dirty, changed_at)
  values (true, true, now())
  on conflict (singleton) do update set dirty = true, changed_at = excluded.changed_at;
  return null;
end;
$$;

drop trigger if exists dice_elo_v11_dirty_games on public.dice_games;
create trigger dice_elo_v11_dirty_games
after insert or delete or update of ranked, winner_team, team1_score, team2_score,
  played_at, created_at, live_result_state on public.dice_games
for each statement execute function public.dice_elo_v11_mark_dirty();

drop trigger if exists dice_elo_v11_dirty_players on public.dice_game_players;
create trigger dice_elo_v11_dirty_players
after insert or delete or update of id, game_id, user_id, team on public.dice_game_players
for each statement execute function public.dice_elo_v11_mark_dirty();

drop trigger if exists dice_elo_v11_dirty_profiles on public.dice_profiles;
create trigger dice_elo_v11_dirty_profiles
after insert or delete or update of user_id, elo_rating, ranked_games_played on public.dice_profiles
for each statement execute function public.dice_elo_v11_mark_dirty();

revoke all on function public.dice_elo_v11_mark_dirty() from public, anon, authenticated;
grant execute on function public.dice_elo_v11_mark_dirty() to service_role;

create or replace function public.dice_elo_v11_source_snapshot()
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
        'ranked_games_played', p.ranked_games_played
      ) order by p.user_id)
      from public.dice_profiles p
    ), '[]'::jsonb),
    'games', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'id', g.id,
          'ranked', g.ranked,
          'winner_team', g.winner_team,
          'team1_score', g.team1_score,
          'team2_score', g.team2_score,
          'played_at', g.played_at,
          'created_at', g.created_at,
          'live_result_state', g.live_result_state
        ) order by g.played_at, g.created_at, g.id
      )
      from public.dice_games g
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'id', gp.id,
          'game_id', gp.game_id,
          'user_id', gp.user_id,
          'team', gp.team
        ) order by gp.game_id, gp.user_id, gp.id
      )
      from public.dice_game_players gp
    ), '[]'::jsonb)
  )
$$;

create or replace function public.dice_elo_v11_state_snapshot()
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
        'elo_v11_rating', p.elo_v11_rating,
        'rating_deviation', p.rating_deviation
      ) order by p.user_id)
      from public.dice_profiles p
    ), '[]'::jsonb),
    'players', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', gp.id,
        'elo_v11_before', gp.elo_v11_before,
        'elo_v11_after', gp.elo_v11_after,
        'rating_deviation_before', gp.rating_deviation_before,
        'rating_deviation_after', gp.rating_deviation_after
      ) order by gp.id)
      from public.dice_game_players gp
    ), '[]'::jsonb),
    'status', coalesce((
      select jsonb_build_object(
        'dirty', status.dirty,
        'changed_at', status.changed_at,
        'promoted_at', status.promoted_at,
        'source_fingerprint', status.source_fingerprint
      )
      from public.dice_elo_v11_refresh_status status
      where status.singleton
    ), jsonb_build_object('dirty', true))
  )
$$;

create or replace function public.dice_elo_v11_promote(
  p_source jsonb,
  p_player_snapshots jsonb,
  p_profile_states jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  current_source jsonb;
  expected_players integer;
  expected_profiles integer;
  updated_players integer;
  updated_profiles integer;
  updated_status integer;
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') <> 'service_role' then
    raise exception using errcode = '42501', message = 'dice_elo_v11.service_role_required';
  end if;
  if p_source is null
     or p_player_snapshots is null
     or p_profile_states is null
     or jsonb_typeof(p_source) <> 'object'
     or jsonb_typeof(p_source->'players') <> 'array'
     or jsonb_typeof(p_source->'profiles') <> 'array'
     or jsonb_typeof(p_player_snapshots) <> 'array'
     or jsonb_typeof(p_profile_states) <> 'array' then
    raise exception using errcode = '22023', message = 'dice_elo_v11.invalid_promotion_payload';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('dice:elo:v1.1:promotion', 0)
  );
  lock table public.dice_games, public.dice_game_players, public.dice_profiles,
    public.dice_elo_v11_refresh_status
    in share row exclusive mode;

  current_source := public.dice_elo_v11_source_snapshot();
  if current_source is distinct from p_source then
    raise exception using errcode = '40001', message = 'dice_elo_v11.source_changed';
  end if;

  expected_players := jsonb_array_length(p_source->'players');
  expected_profiles := jsonb_array_length(p_source->'profiles');
  if jsonb_array_length(p_player_snapshots) <> expected_players
     or jsonb_array_length(p_profile_states) <> expected_profiles then
    raise exception using errcode = '22023', message = 'dice_elo_v11.incomplete_promotion';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(p_profile_states) item
    where jsonb_typeof(item) <> 'object'
       or not (item ?& array['user_id', 'elo_v11_rating', 'rating_deviation'])
       or jsonb_typeof(item->'user_id') <> 'string'
       or jsonb_typeof(item->'elo_v11_rating') <> 'number'
       or jsonb_typeof(item->'rating_deviation') <> 'number'
  ) or exists (
    select 1
    from jsonb_array_elements(p_player_snapshots) item
    where jsonb_typeof(item) <> 'object'
       or not (item ?& array[
         'id', 'elo_v11_before', 'elo_v11_after',
         'rating_deviation_before', 'rating_deviation_after'
       ])
       or jsonb_typeof(item->'id') <> 'string'
       or jsonb_typeof(item->'elo_v11_before') not in ('number', 'null')
       or jsonb_typeof(item->'elo_v11_after') not in ('number', 'null')
       or jsonb_typeof(item->'rating_deviation_before') not in ('number', 'null')
       or jsonb_typeof(item->'rating_deviation_after') not in ('number', 'null')
       or (
         (jsonb_typeof(item->'elo_v11_before') = 'number')::integer
         + (jsonb_typeof(item->'elo_v11_after') = 'number')::integer
         + (jsonb_typeof(item->'rating_deviation_before') = 'number')::integer
         + (jsonb_typeof(item->'rating_deviation_after') = 'number')::integer
       ) not in (0, 4)
  ) then
    raise exception using errcode = '22023', message = 'dice_elo_v11.invalid_promotion_values';
  end if;
  if exists (
    (select row_data.id
       from jsonb_to_recordset(p_player_snapshots) as row_data(id uuid)
     except
     select row_data.id
       from jsonb_to_recordset(p_source->'players') as row_data(id uuid))
    union all
    (select row_data.id
       from jsonb_to_recordset(p_source->'players') as row_data(id uuid)
     except
     select row_data.id
       from jsonb_to_recordset(p_player_snapshots) as row_data(id uuid))
  ) or exists (
    (select row_data.user_id
       from jsonb_to_recordset(p_profile_states) as row_data(user_id uuid)
     except
     select row_data.user_id
       from jsonb_to_recordset(p_source->'profiles') as row_data(user_id uuid))
    union all
    (select row_data.user_id
       from jsonb_to_recordset(p_source->'profiles') as row_data(user_id uuid)
     except
     select row_data.user_id
       from jsonb_to_recordset(p_profile_states) as row_data(user_id uuid))
  ) then
    raise exception using errcode = '22023', message = 'dice_elo_v11.promotion_identity_mismatch';
  end if;

  update public.dice_game_players gp set
    elo_v11_before = snapshot.elo_v11_before,
    elo_v11_after = snapshot.elo_v11_after,
    rating_deviation_before = snapshot.rating_deviation_before,
    rating_deviation_after = snapshot.rating_deviation_after
  from jsonb_to_recordset(p_player_snapshots) as snapshot(
    id uuid,
    elo_v11_before integer,
    elo_v11_after integer,
    rating_deviation_before numeric,
    rating_deviation_after numeric
  )
  where gp.id = snapshot.id;
  get diagnostics updated_players = row_count;

  update public.dice_profiles profile set
    elo_v11_rating = state.elo_v11_rating,
    rating_deviation = state.rating_deviation
  from jsonb_to_recordset(p_profile_states) as state(
    user_id uuid,
    elo_v11_rating integer,
    rating_deviation numeric
  )
  where profile.user_id = state.user_id;
  get diagnostics updated_profiles = row_count;

  if updated_players <> expected_players or updated_profiles <> expected_profiles then
    raise exception using errcode = 'P0001', message = 'dice_elo_v11.promotion_row_count_mismatch';
  end if;

  update public.dice_elo_v11_refresh_status set
    dirty = false,
    promoted_at = now(),
    source_fingerprint = md5(p_source::text)
  where singleton;
  get diagnostics updated_status = row_count;
  if updated_status <> 1 then
    raise exception using errcode = 'P0001', message = 'dice_elo_v11.refresh_status_missing';
  end if;

  return jsonb_build_object(
    'players_updated', updated_players,
    'profiles_updated', updated_profiles,
    'state', public.dice_elo_v11_state_snapshot()
  );
end;
$$;

revoke all on function public.dice_elo_v11_source_snapshot() from public, anon, authenticated;
revoke all on function public.dice_elo_v11_state_snapshot() from public, anon, authenticated;
revoke all on function public.dice_elo_v11_promote(jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.dice_elo_v11_source_snapshot() to service_role;
grant execute on function public.dice_elo_v11_state_snapshot() to service_role;
grant execute on function public.dice_elo_v11_promote(jsonb, jsonb, jsonb) to service_role;
