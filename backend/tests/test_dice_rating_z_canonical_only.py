import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from dice.rating_replay import build_rating_plan, project_game_mutation
from tests.dice_test_database import is_isolated_dice_test_database


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "backend/migrations/0064_dice_canonical_rating_only.sql"
LIVE_RANKED_MIGRATION = ROOT / "backend/migrations/0070_dice_live_ranked_canonical_mutation.sql"
LIVE_SETTINGS_MIGRATION = ROOT / "backend/migrations/0071_dice_live_ranked_settings_concurrency.sql"
LIVE_REPAIR_MIGRATION = ROOT / "backend/migrations/0072_dice_live_rating_repair_queue.sql"
LIVE_LIFECYCLE_MIGRATION = ROOT / "backend/migrations/0073_dice_live_atomic_lifecycle.sql"
MANUAL_UPDATE_MIGRATION = ROOT / "backend/migrations/0074_dice_manual_game_update_concurrency.sql"
DUO_SNAPSHOT_FIX_FORWARD = ROOT / "backend/migrations/0075_dice_duo_snapshot_fix_forward.sql"
PROFILE_INVARIANTS = ROOT / "backend/migrations/0063_dice_canonical_rating_profile_invariants.sql"
ACTIVATION = ROOT / "backend/migrations/0058_dice_canonical_rating_activation.sql"
FILL_FORWARD = ROOT / "backend/migrations/0059_dice_canonical_rating_fill_forward.sql"

pytestmark = pytest.mark.skipif(
    not is_isolated_dice_test_database(os.environ),
    reason="requires an allowlisted isolated PostgreSQL database",
)


def _psql(sql: str) -> subprocess.CompletedProcess[str]:
    database_url = os.environ.get("DB_URL")
    if not database_url:
        pytest.skip("DB_URL is required for PostgreSQL transaction tests")
    return subprocess.run(
        ["psql", database_url, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )


def _json_arg(value: object) -> str:
    return "$json$" + json.dumps(value, separators=(",", ":")) + "$json$::jsonb"


def test_profile_invariants_still_fail_closed():
    valid = _psql(f"begin;\n\\i {PROFILE_INVARIANTS}\nrollback;\n")
    assert valid.returncode == 0, valid.stdout + valid.stderr

    invalid = _psql(rf"""
begin;
alter table public.dice_profiles drop constraint if exists dice_profiles_rating_deviation_check;
alter table public.dice_profiles alter column rating_deviation drop not null;
update public.dice_profiles set rating_deviation = null
where user_id = (select user_id from public.dice_profiles order by user_id limit 1);
\i {PROFILE_INVARIANTS}
rollback;
""")
    assert invalid.returncode != 0
    assert "dice_rating.canonical_profile_state_required" in invalid.stderr


def test_canonical_only_migration_is_idempotent_and_removes_control_plane():
    result = _psql(rf"""
begin;
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
alter table public.dice_games add constraint dice_games_live_results_unranked check (source_live_match_id is null or not ranked);
\i {MIGRATION}
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
alter table public.dice_games add constraint dice_games_live_results_unranked check (source_live_match_id is null or not ranked);
\i {MIGRATION}
do $$
declare
  mutation_definition text;
  live_definition text;
begin
  if to_regclass('public.dice_rating_control') is not null
     or to_regprocedure('public.dice_rating_generation_snapshot()') is not null
     or to_regprocedure('public.dice_rating_commit_and_activate(jsonb,jsonb,jsonb,text,text)') is not null
     or to_regprocedure('public.dice_rating_control_snapshot()') is not null
     or to_regprocedure('public.dice_rating_mark_dirty()') is not null
     or to_regprocedure('public.dice_rating_status()') is not null
     or to_regprocedure('public.dice_rating_refresh_if_active(jsonb,jsonb,jsonb,text,text)') is not null
     or exists (
       select 1 from pg_trigger
       where tgname in ('dice_rating_dirty_games', 'dice_rating_dirty_players', 'dice_rating_dirty_profiles')
         and not tgisinternal
     ) then
    raise exception 'retired rating control plane still exists';
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_games'::regclass
      and conname = 'dice_games_live_results_unranked'
      and convalidated
  ) then
    raise exception 'live-result unranked invariant is missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.dice_games'::regclass
      and tgname = 'dice_live_result_write_guard'
      and not tgisinternal
  ) then
    raise exception 'live-result write guard is missing';
  end if;

  mutation_definition := pg_get_functiondef(
    'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)'::regprocedure
  );
  live_definition := pg_get_functiondef(
    'public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text)'::regprocedure
  );
  if mutation_definition like '%dice_rating_control%'
     or mutation_definition like '%cutover_required%'
     or live_definition not like '%dice:elo:canonical%' then
    raise exception 'canonical runtime still depends on retired reconciliation';
  end if;
  if has_function_privilege(
       'anon',
       'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)',
       'execute'
     ) or has_function_privilege(
       'authenticated',
       'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)',
       'execute'
     ) or not has_function_privilege(
       'service_role',
       'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)',
       'execute'
     ) then
    raise exception 'canonical mutation privileges are incorrect';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "control_update",
    ["canonical_active = false, dirty = false", "canonical_active = true, dirty = true"],
)
def test_canonical_only_migration_refuses_inactive_or_dirty_existing_state(control_update):
    result = _psql(rf"""
begin;
\i {ACTIVATION}
\i {FILL_FORWARD}
update public.dice_rating_control set {control_update} where singleton;
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
alter table public.dice_games add constraint dice_games_live_results_unranked check (source_live_match_id is null or not ranked);
\i {MIGRATION}
rollback;
""")
    assert result.returncode != 0
    assert "dice_rating.clean_canonical_state_required" in result.stderr


def test_live_materialized_games_reject_manual_update_and_delete():
    result = _psql(rf"""
begin;
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
alter table public.dice_games add constraint dice_games_live_results_unranked check (source_live_match_id is null or not ranked);
\i {MIGRATION}
insert into public.dice_live_matches (
  id, created_by, team_order, teams, rules_snapshot
) values (
  '71000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  '["one","two"]'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb
);
select set_config('dice.live_materialization', 'on', true);
update public.dice_games
set ranked = false,
    source_live_match_id = '71000000-0000-0000-0000-000000000001'
where id = '10000000-0000-0000-0000-000000000001';
select set_config('dice.live_materialization', '', true);
do $$
begin
  begin
    update public.dice_games set team1_score = team1_score + 1
    where id = '10000000-0000-0000-0000-000000000001';
    raise exception 'manual live-result update unexpectedly succeeded';
  exception when sqlstate '55000' then
    if sqlerrm <> 'dice_live.result_managed_by_live_match' then raise; end if;
  end;
  begin
    delete from public.dice_games
    where id = '10000000-0000-0000-0000-000000000001';
    raise exception 'manual live-result delete unexpectedly succeeded';
  exception when sqlstate '55000' then
    if sqlerrm <> 'dice_live.result_managed_by_live_match' then raise; end if;
  end;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_live_ranked_mutation_removes_unranked_constraint_but_keeps_guard():
    result = _psql(rf"""
begin;
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
alter table public.dice_games add constraint dice_games_live_results_unranked check (source_live_match_id is null or not ranked);
\i {MIGRATION}
\i {LIVE_RANKED_MIGRATION}
do $$
begin
  if exists (
    select 1 from pg_constraint
    where conrelid = 'public.dice_games'::regclass
      and conname = 'dice_games_live_results_unranked'
  ) then
    raise exception 'live ranked constraint still blocks canonical promotion';
  end if;
  if pg_get_functiondef(
       'public.dice_live_result_write_guard()'::regprocedure
     ) not like '%dice.rating_mutation%' then
    raise exception 'live guard does not recognize canonical rating mutation';
  end if;
  if pg_get_functiondef(
       'public.dice_rating_apply_game_mutation(uuid,jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb,text,text,text,text)'::regprocedure
     ) not like '%dice.rating_mutation%' then
    raise exception 'canonical mutation does not open the guarded write scope';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_live_ranked_settings_migration_is_private_and_repairs_mismatches():
    result = _psql(rf"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
do $$
declare owner_id uuid;
begin
  select user_id into owner_id from public.dice_profiles order by user_id limit 1;
  insert into public.dice_live_matches (
    id, created_by, team_order, teams, rules_snapshot, ranked
  ) values (
    '76000000-0000-0000-0000-000000000001', owner_id,
    '["one","two"]'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, false
  );
  insert into public.dice_games (
    id, created_by, ranked, team1_score, team2_score, winner_team,
    played_at, source_live_match_id, live_result_state
  ) values (
    '76000000-0000-0000-0000-000000000002', owner_id, true, 5, 1, 1,
    '2035-01-01T00:00:00Z', '76000000-0000-0000-0000-000000000001', 'official'
  );
  insert into public.dice_live_matches (
    id, created_by, team_order, teams, rules_snapshot, ranked
  ) values (
    '76000000-0000-0000-0000-000000000003', owner_id,
    '["one","two"]'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, false
  );
end
$$;
\i {LIVE_SETTINGS_MIGRATION}
\i {LIVE_SETTINGS_MIGRATION}
do $$
declare status jsonb;
begin
  if not (select ranked from public.dice_live_matches where id = '76000000-0000-0000-0000-000000000001') then
    raise exception 'migration did not backfill the materialized result mismatch';
  end if;
  update public.dice_live_matches set ranked = false
  where id = '76000000-0000-0000-0000-000000000001';
  perform set_config('dice.rating_mutation', 'on', true);
  update public.dice_games set ranked = ranked
  where id = '76000000-0000-0000-0000-000000000002';
  if not (select ranked from public.dice_live_matches where id = '76000000-0000-0000-0000-000000000001') then
    raise exception 'same-value canonical update did not repair the live flag';
  end if;
  status := public.dice_live_set_ranked(
    '76000000-0000-0000-0000-000000000003', true
  );
  if status->>'status' <> 'updated'
     or not (select ranked from public.dice_live_matches where id = '76000000-0000-0000-0000-000000000003') then
    raise exception 'pre-materialization setting was not applied';
  end if;
  if has_function_privilege('anon', 'public.dice_live_set_ranked(uuid,boolean)', 'execute')
     or has_function_privilege('authenticated', 'public.dice_live_set_ranked(uuid,boolean)', 'execute')
     or not has_function_privilege('service_role', 'public.dice_live_set_ranked(uuid,boolean)', 'execute')
     or has_function_privilege('service_role', 'public.dice_live_sync_ranked_from_result()', 'execute') then
    raise exception 'live settings function privileges are incorrect';
  end if;
  if not exists (
    select 1 from pg_proc
    where oid = 'public.dice_live_set_ranked(uuid,boolean)'::regprocedure
      and proconfig @> array['lock_timeout=2s']
  ) then
    raise exception 'settings-specific lock timeout is missing';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_duo_snapshot_fix_forward_excludes_duo_history_and_requeues_live_ratings():
    result = _psql(rf"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
do $$
declare owner_id uuid;
begin
  select user_id into owner_id from public.dice_profiles order by user_id limit 1;
  insert into public.dice_live_matches (
    id, created_by, team_order, teams, rules_snapshot, ranked
  ) values (
    '75000000-0000-0000-0000-000000000001', owner_id,
    '["one","two"]'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, true
  );
  perform set_config('dice.live_materialization', 'on', true);
  insert into public.dice_games (
    id, created_by, ranked, team1_score, team2_score, winner_team,
    played_at, source_live_match_id, live_result_state
  ) values (
    '75000000-0000-0000-0000-000000000002', owner_id, true, 1, 0, 1,
    '2035-01-01T00:00:00Z', '75000000-0000-0000-0000-000000000001', 'official'
  );
  update public.dice_live_matches
  set official_result_id = '75000000-0000-0000-0000-000000000002'
  where id = '75000000-0000-0000-0000-000000000001';
  delete from public.dice_live_rating_repairs
  where match_id = '75000000-0000-0000-0000-000000000001';
  insert into public.dice_games (
    id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at
  ) values (
    '75000000-0000-0000-0000-000000000003', owner_id, true, true, 5, 1, 1,
    '2034-01-01T00:00:00Z'
  );
  insert into public.dice_game_players (
    game_id, user_id, team, elo_before, elo_after,
    rating_deviation_before, rating_deviation_after
  ) select
    '75000000-0000-0000-0000-000000000003', user_id,
    (row_number() over (order by user_id))::smallint, 1500, 1525, 350, 297.5
  from public.dice_profiles order by user_id limit 2;
  execute replace(
    pg_get_functiondef('public.dice_rating_source_snapshot()'::regprocedure),
    E'        where g.duo_only is not true\n', ''
  );
  execute replace(
    pg_get_functiondef('public.dice_rating_state_snapshot()'::regprocedure),
    E'      where g.duo_only is not true\n', ''
  );
  execute replace(
    pg_get_functiondef('public.dice_rating_analytics_snapshot()'::regprocedure),
    E'        and g.duo_only is not true\n', ''
  );
  if not exists (
    select 1 from jsonb_array_elements(public.dice_rating_source_snapshot()->'games') game
    where game->>'id' = '75000000-0000-0000-0000-000000000003'
  ) then
    raise exception 'test did not reproduce the stale duo snapshot boundary';
  end if;
end
$$;
\i {DUO_SNAPSHOT_FIX_FORWARD}
do $$
begin
  if exists (
    select 1
    from jsonb_array_elements(public.dice_rating_source_snapshot()->'games') game
    join public.dice_games stored on stored.id = (game->>'id')::uuid
    where stored.duo_only
  ) or exists (
    select 1
    from jsonb_array_elements(public.dice_rating_state_snapshot()->'players') snapshot
    join public.dice_game_players player on player.id = (snapshot->>'id')::uuid
    join public.dice_games game on game.id = player.game_id
    where game.duo_only
  ) or exists (
    select 1
    from jsonb_array_elements(public.dice_rating_analytics_snapshot()->'games') game
    where coalesce((game->>'duo_only')::boolean, false)
  ) then
    raise exception 'duo-only history leaked through an individual rating snapshot';
  end if;
  if exists (
    select 1 from public.dice_game_players
    where game_id = '75000000-0000-0000-0000-000000000003'
      and (elo_before is not null or elo_after is not null
        or rating_deviation_before is not null or rating_deviation_after is not null)
  ) then
    raise exception 'duo-only history retained individual rating snapshots';
  end if;
  if not exists (
    select 1 from public.dice_live_rating_repairs
    where match_id = '75000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'ranked live result was not requeued after the snapshot repair';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_completed_live_ranked_settings_bound_cross_process_lock_contention():
    database_url = os.environ.get("DB_URL")
    if not database_url:
        pytest.skip("DB_URL is required for PostgreSQL transaction tests")
    writer = subprocess.Popen(
        ["psql", database_url, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert writer.stdin is not None
    writer.stdin.write(r"""
begin;
select pg_advisory_xact_lock(hashtextextended('dice:elo:canonical', 0));
\echo LOCK_ACQUIRED
select pg_sleep(3);
commit;
""")
    writer.stdin.close()
    assert writer.stdout is not None
    while True:
        line = writer.stdout.readline()
        assert line, "lock holder exited before acquiring the canonical lock"
        if "LOCK_ACQUIRED" in line:
            break

    started = time.monotonic()
    contender = _psql("""
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_live_apply_ranked_rating_mutation(
  '76000000-0000-0000-0000-000000000099',
  '{}'::jsonb,
  'update',
  '{"id":"76000000-0000-0000-0000-000000000002","created_by":"76000000-0000-0000-0000-000000000010","ranked":true,"team1_score":5,"team2_score":1,"winner_team":1,"played_at":"2035-01-01T00:00:00Z","created_at":"2035-01-01T00:00:00Z","tournament_id":null}'::jsonb,
  '[{"id":"76000000-0000-0000-0000-000000000011","user_id":"76000000-0000-0000-0000-000000000010","team":1,"counts_for_group_stage":true,"self_sinks":0,"sinks":0},{"id":"76000000-0000-0000-0000-000000000012","user_id":"76000000-0000-0000-0000-000000000013","team":2,"counts_for_group_stage":true,"self_sinks":0,"sinks":0}]'::jsonb,
  '{}'::jsonb,
  '[]'::jsonb,
  '[]'::jsonb,
  repeat('0', 64),
  repeat('1', 64),
  null,
  null
);
""")
    elapsed = time.monotonic() - started
    writer.wait(timeout=5)

    assert contender.returncode != 0
    assert "lock timeout" in contender.stderr
    assert elapsed < 2.8


def test_live_rating_repair_queue_is_transactional_private_and_idempotent():
    result = _psql(rf"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
\i {LIVE_REPAIR_MIGRATION}
\i {LIVE_REPAIR_MIGRATION}
do $$
declare owner_id uuid;
begin
  select user_id into owner_id from public.dice_profiles order by user_id limit 1;
  insert into public.dice_live_matches (
    id, created_by, team_order, teams, rules_snapshot, ranked
  ) values (
    '77000000-0000-0000-0000-000000000001', owner_id,
    '["one","two"]'::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, true
  );
  perform set_config('dice.live_materialization', 'on', true);
  insert into public.dice_games (
    id, created_by, ranked, team1_score, team2_score, winner_team,
    played_at, source_live_match_id, live_result_state
  ) values (
    '77000000-0000-0000-0000-000000000002', owner_id, true, 5, 1, 1,
    '2035-01-01T00:00:00Z', '77000000-0000-0000-0000-000000000001', 'official'
  );
  if not exists (
    select 1 from public.dice_live_rating_repairs
    where match_id = '77000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'live materialization did not enqueue rating repair';
  end if;
  begin
    perform set_config('dice.rating_mutation', 'on', true);
    update public.dice_games set ranked = ranked
    where id = '77000000-0000-0000-0000-000000000002';
    raise exception 'simulated later canonical failure';
  exception when others then
    null;
  end;
  if not exists (
    select 1 from public.dice_live_rating_repairs
    where match_id = '77000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'failed canonical transaction incorrectly acknowledged repair';
  end if;
  perform set_config('dice.rating_mutation', 'on', true);
  update public.dice_games set ranked = ranked
  where id = '77000000-0000-0000-0000-000000000002';
  if exists (
    select 1 from public.dice_live_rating_repairs
    where match_id = '77000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'canonical mutation did not acknowledge rating repair';
  end if;
  insert into public.dice_live_rating_repairs (match_id)
  values ('77000000-0000-0000-0000-000000000001');
  delete from public.dice_games
  where id = '77000000-0000-0000-0000-000000000002';
  if exists (
    select 1 from public.dice_live_rating_repairs
    where match_id = '77000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'canonical deletion did not acknowledge rating repair';
  end if;
  if has_table_privilege('anon', 'public.dice_live_rating_repairs', 'select')
     or has_table_privilege('authenticated', 'public.dice_live_rating_repairs', 'select')
     or has_function_privilege('service_role', 'public.dice_live_track_rating_repair()', 'execute') then
    raise exception 'rating repair queue is exposed';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_live_creation_and_creator_membership_commit_atomically():
    result = _psql(rf"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
\i {LIVE_LIFECYCLE_MIGRATION}
create or replace function pg_temp.reject_referee()
returns trigger language plpgsql as $$
begin
  raise exception 'synthetic membership failure';
end;
$$;
create trigger reject_referee before insert on public.dice_live_referees
for each row execute function pg_temp.reject_referee();
do $$
declare
  owner_id uuid;
  players uuid[];
  before_count bigint;
begin
  select array_agg(user_id order by user_id) into players
  from (select user_id from public.dice_profiles order by user_id limit 4) profiles;
  owner_id := players[1];
  select count(*) into before_count from public.dice_live_matches;
  begin
    perform public.dice_live_create_match(
      '73000000-0000-0000-0000-000000000001', owner_id, '["blue","clay"]',
      jsonb_build_object('blue', jsonb_build_array(players[1], players[2]),
                         'clay', jsonb_build_array(players[3], players[4])),
      '{{}}', '{{}}', null, true
    );
  exception when others then
    null;
  end;
  if (select count(*) from public.dice_live_matches) <> before_count then
    raise exception 'failed creator membership left an orphaned live match';
  end if;
end
$$;
drop trigger reject_referee on public.dice_live_referees;
do $$
declare
  owner_id uuid;
  players uuid[];
  created jsonb;
begin
  select array_agg(user_id order by user_id) into players
  from (select user_id from public.dice_profiles order by user_id limit 4) profiles;
  owner_id := players[1];
  created := public.dice_live_create_match(
    '73000000-0000-0000-0000-000000000002', owner_id, '["blue","clay"]',
    jsonb_build_object('blue', jsonb_build_array(players[1], players[2]),
                       'clay', jsonb_build_array(players[3], players[4])),
    '{{}}', '{{}}', null, true
  );
  if not exists (
    select 1 from public.dice_live_referees
    where match_id = (created->>'id')::uuid and user_id = owner_id
  ) then
    raise exception 'creator membership did not commit with live match';
  end if;
  if (public.dice_live_create_match(
    '73000000-0000-0000-0000-000000000002', owner_id, '["blue","clay"]',
    jsonb_build_object('blue', jsonb_build_array(players[1], players[2]),
                       'clay', jsonb_build_array(players[3], players[4])),
    '{{}}', '{{}}', null, true
  )->>'id') is distinct from created->>'id' then
    raise exception 'identical create retry returned a different match';
  end if;
  begin
    perform public.dice_live_create_match(
      '73000000-0000-0000-0000-000000000002', owner_id, '["blue","clay"]',
      jsonb_build_object('blue', jsonb_build_array(players[1], players[2]),
                         'clay', jsonb_build_array(players[3], players[4])),
      '{{}}', '{{}}', null, false
    );
    raise exception 'conflicting create retry was accepted';
  exception when unique_violation then
    if sqlerrm <> 'dice_live.create_idempotency_conflict' then raise; end if;
  end;
  update public.dice_live_matches set deleted_at = now(), deleted_by = owner_id
  where id = '73000000-0000-0000-0000-000000000002';
  begin
    perform public.dice_live_create_match(
      '73000000-0000-0000-0000-000000000002', owner_id, '["blue","clay"]',
      jsonb_build_object('blue', jsonb_build_array(players[1], players[2]),
                         'clay', jsonb_build_array(players[3], players[4])),
      '{{}}', '{{}}', null, true
    );
    raise exception 'deleted match was resurrected by a create retry';
  exception when unique_violation then
    if sqlerrm <> 'dice_live.create_idempotency_conflict' then raise; end if;
  end;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_live_command_waiting_on_delete_cannot_resurrect_match():
    database_url = os.environ.get("DB_URL")
    if not database_url:
        pytest.skip("DB_URL is required for PostgreSQL transaction tests")
    match_id = "7a000000-0000-0000-0000-000000000001"
    event_id = "7a000000-0000-0000-0000-000000000002"
    owner = _psql(r"""
\pset tuples_only on
\pset format unaligned
select user_id from public.dice_profiles order by user_id limit 1;
""")
    assert owner.returncode == 0, owner.stdout + owner.stderr
    owner_id = owner.stdout.strip().splitlines()[-1]
    setup = _psql(f"""
insert into public.dice_live_matches (id, created_by, team_order, teams, rules_snapshot)
values ('{match_id}', '{owner_id}', '["blue","clay"]', '{{}}', '{{}}');
insert into public.dice_live_referees (match_id, user_id) values ('{match_id}', '{owner_id}');
""")
    assert setup.returncode == 0, setup.stdout + setup.stderr

    deleter = subprocess.Popen(
        ["psql", database_url, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert deleter.stdin is not None
    deleter.stdin.write(rf"""
begin;
select pg_advisory_xact_lock(hashtextextended('dice:elo:canonical', 0));
update public.dice_live_matches set deleted_at = now(), deleted_by = '{owner_id}'
where id = '{match_id}';
\echo TOMBSTONED
select pg_sleep(1);
commit;
""")
    deleter.stdin.close()
    assert deleter.stdout is not None
    while True:
        line = deleter.stdout.readline()
        assert line, "deleter exited before tombstoning the live match"
        if "TOMBSTONED" in line:
            break

    try:
        contender = _psql(f"""
set request.jwt.claims = '{{"role":"service_role"}}';
select public.dice_live_append_command(
  '{match_id}', '{owner_id}', 'late-command', 0, '{{}}',
  '[{{"id":"{event_id}","kind":"point"}}]',
  '{{"score":[1,0],"status":"active","coverage":"complete","observations":1,"stats":{{}}}}',
  array[1,0]::smallint[], 'active', 'complete'
);
""")
        deleter.wait(timeout=5)
        assert contender.returncode != 0
        assert "dice_live.match_not_found" in contender.stderr
        counts = _psql(rf"""
\pset tuples_only on
\pset format unaligned
select (select count(*) from public.dice_live_commands where match_id = '{match_id}'),
       (select count(*) from public.dice_games where source_live_match_id = '{match_id}');
""")
        assert counts.returncode == 0, counts.stdout + counts.stderr
        assert counts.stdout.strip().splitlines()[-1] == "0|0"
    finally:
        if deleter.poll() is None:
            deleter.kill()
            deleter.wait(timeout=5)
        cleanup = _psql(f"delete from public.dice_live_matches where id = '{match_id}';")
        assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr


def test_live_tombstone_failure_rolls_back_canonical_delete():
    captured = _psql(r"""
\pset tuples_only on
\pset format unaligned
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_rating_source_snapshot();
""")
    assert captured.returncode == 0, captured.stdout + captured.stderr
    source = json.loads(captured.stdout.strip().splitlines()[-1])
    game = source["games"][0]
    plan = build_rating_plan(project_game_mutation(source, "delete", {"id": game["id"]}, []))
    deleted_by = source["profiles"][0]["user_id"]

    failed = _psql(f"""
set request.jwt.claims = '{{"role":"service_role"}}';
select public.dice_live_delete_with_rating_mutation(
  '78000000-0000-0000-0000-000000000001',
  {_json_arg(source)}, 'delete', {_json_arg({"id": game["id"]})}, '[]'::jsonb,
  {_json_arg(plan.source)}, {_json_arg(plan.player_snapshots)},
  {_json_arg(plan.profile_states)}, '{plan.source_digest}', '{plan.output_digest}',
  null, null, '78000000-0000-0000-0000-000000000002', '{deleted_by}'
);
""")
    assert failed.returncode != 0
    assert "dice_live.delete_source_changed" in failed.stderr

    survived = _psql(
        f"\\pset tuples_only on\nselect count(*) from public.dice_games where id = '{game['id']}';"
    )
    assert survived.returncode == 0
    assert survived.stdout.strip() == "1"


def test_live_delete_wrapper_exact_replay_is_idempotent():
    initial = _psql(r"""
\pset tuples_only on
\pset format unaligned
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_rating_source_snapshot();
""")
    assert initial.returncode == 0, initial.stdout + initial.stderr
    source = json.loads(initial.stdout.strip().splitlines()[-1])
    game = source["games"][0]
    deleted_by = source["profiles"][0]["user_id"]
    setup = _psql(f"""
set request.jwt.claims = '{{"role":"service_role"}}';
insert into public.dice_live_matches (
  id, created_by, team_order, teams, rules_snapshot, ranked, status,
  official_result_id
) values (
  '79000000-0000-0000-0000-000000000002', '{deleted_by}',
  '["blue","clay"]', '{{}}', '{{}}', false, 'completed', '{game["id"]}'
);
select set_config('dice.live_materialization', 'on', false);
update public.dice_games
set source_live_match_id = '79000000-0000-0000-0000-000000000002'
where id = '{game["id"]}' and source_live_match_id is null;
""")
    assert setup.returncode == 0, setup.stdout + setup.stderr

    captured = _psql(r"""
\pset tuples_only on
\pset format unaligned
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_rating_source_snapshot();
""")
    assert captured.returncode == 0, captured.stdout + captured.stderr
    source = json.loads(captured.stdout.strip().splitlines()[-1])
    game = next(row for row in source["games"] if row["id"] == game["id"])
    plan = build_rating_plan(project_game_mutation(source, "delete", {"id": game["id"]}, []))
    call = f"""public.dice_live_delete_with_rating_mutation(
      '79000000-0000-0000-0000-000000000001',
      {_json_arg(source)}, 'delete', {_json_arg({"id": game["id"]})}, '[]'::jsonb,
      {_json_arg(plan.source)}, {_json_arg(plan.player_snapshots)},
      {_json_arg(plan.profile_states)}, '{plan.source_digest}', '{plan.output_digest}',
      '{deleted_by}', '{"b" * 64}',
      '79000000-0000-0000-0000-000000000002', '{deleted_by}'
    )"""

    try:
        result = _psql(f"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
do $$
declare replayed jsonb;
begin
  perform {call};
  replayed := {call};
  if replayed->>'replayed' <> 'true'
     or exists (select 1 from public.dice_games where id = '{game["id"]}')
     or not exists (
       select 1 from public.dice_live_matches
       where id = '79000000-0000-0000-0000-000000000002'
         and deleted_at is not null and deleted_by = '{deleted_by}'
     ) then
    raise exception 'exact live delete replay was not side-effect-free';
  end if;
end
$$;
rollback;
""")
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        cleanup = _psql(f"""
set request.jwt.claims = '{{"role":"service_role"}}';
select set_config('dice.live_materialization', 'on', false);
update public.dice_games set source_live_match_id = null where id = '{game["id"]}';
delete from public.dice_live_matches where id = '79000000-0000-0000-0000-000000000002';
""")
        assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr


def test_surviving_wrapper_atomically_creates_updates_deletes_and_replays_receipts():
    captured = _psql(r"""
\pset tuples_only on
\pset format unaligned
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_rating_source_snapshot();
""")
    assert captured.returncode == 0, captured.stdout + captured.stderr
    source = json.loads(captured.stdout.strip().splitlines()[-1])
    baseline = build_rating_plan(source)
    users = [row["user_id"] for row in source["profiles"][:2]]
    assert len(users) == 2
    game = {
        "id": "72000000-0000-0000-0000-000000000001",
        "created_by": users[0], "ranked": True,
        "team1_score": 11, "team2_score": 7, "winner_team": 1,
        "played_at": "2035-01-01T00:00:00+00:00",
        "created_at": "2035-01-01T00:00:00+00:00",
        "tournament_id": None, "source_live_match_id": None,
        "live_result_state": None, "termination_reason": None,
        "detail_coverage": "complete", "stats_complete": True,
    }
    create_players = [
        {"id": f"73000000-0000-0000-0000-00000000000{index}",
         "user_id": user_id, "team": index, "counts_for_group_stage": True,
         "self_sinks": 0, "sinks": 0}
        for index, user_id in enumerate(users, 1)
    ]
    created = build_rating_plan(project_game_mutation(source, "create", game, create_players))
    updated_game = {**game, "team1_score": 6, "team2_score": 11, "winner_team": 2}
    update_players = [
        {**player, "id": player["id"].replace("73000000", "74000000")}
        for player in create_players
    ]
    updated = build_rating_plan(
        project_game_mutation(created.source, "update", updated_game, update_players)
    )
    deleted = build_rating_plan(project_game_mutation(updated.source, "delete", game, []))

    def call(mutation_id, plan_before, operation, game_payload, players, plan_after, fingerprint):
        return (
            f"public.dice_rating_apply_game_mutation('{mutation_id}'::uuid, "
            f"{_json_arg(plan_before.source)}, '{operation}', {_json_arg(game_payload)}, "
            f"{_json_arg(players)}, {_json_arg(plan_after.source)}, "
            f"{_json_arg(plan_after.player_snapshots)}, {_json_arg(plan_after.profile_states)}, "
            f"'{plan_after.source_digest}', '{plan_after.output_digest}', "
            f"'{users[0]}', {('$q$' + fingerprint + '$q$') if fingerprint else 'null'})"
        )

    create_call = call(
        "75000000-0000-0000-0000-000000000001", baseline, "create",
        game, create_players, created, "a" * 64,
    )
    update_call = call(
        "75000000-0000-0000-0000-000000000002", created, "update",
        updated_game, update_players, updated, None,
    )
    delete_call = call(
        "75000000-0000-0000-0000-000000000003", updated, "delete",
        {"id": game["id"]}, [], deleted, None,
    )
    result = _psql(f"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
do $$
declare first_receipt jsonb;
declare replay_receipt jsonb;
begin
  first_receipt := {create_call};
  replay_receipt := {create_call};
  if first_receipt ? 'replayed' or replay_receipt->>'replayed' <> 'true' then
    raise exception 'create receipt replay was not side-effect-free';
  end if;
  perform {update_call};
  perform {delete_call};
  if public.dice_rating_source_snapshot() is distinct from {_json_arg(source)}
     or public.dice_rating_state_snapshot() is distinct from {_json_arg({"players": baseline.player_snapshots, "profiles": baseline.profile_states})} then
    raise exception 'create/update/delete did not restore the canonical generation';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_manual_update_wrapper_rejects_a_stale_revision_without_partial_state():
    captured = _psql(r"""
\pset tuples_only on
\pset format unaligned
set request.jwt.claims = '{"role":"service_role"}';
select public.dice_rating_source_snapshot();
""")
    assert captured.returncode == 0, captured.stdout + captured.stderr
    source = json.loads(captured.stdout.strip().splitlines()[-1])
    game = next(row for row in source["games"] if row.get("source_live_match_id") is None)
    players = [row for row in source["players"] if row["game_id"] == game["id"]]
    assert players

    revision_result = _psql(rf"""
\pset tuples_only on
\pset format unaligned
select updated_at from public.dice_games where id = '{game["id"]}';
""")
    assert revision_result.returncode == 0, revision_result.stdout + revision_result.stderr
    original_revision = revision_result.stdout.strip().splitlines()[-1]

    first_game = {**game, "team1_score": 21, "team2_score": 19, "winner_team": 1}
    first_players = [
        {**player, "id": f"76000000-0000-0000-0000-{index:012d}"}
        for index, player in enumerate(players, 1)
    ]
    first_plan = build_rating_plan(
        project_game_mutation(source, "update", first_game, first_players)
    )
    stale_game = {**game, "team1_score": 7, "team2_score": 11, "winner_team": 2}
    stale_players = [
        {**player, "id": f"77000000-0000-0000-0000-{index:012d}"}
        for index, player in enumerate(players, 1)
    ]
    stale_plan = build_rating_plan(
        project_game_mutation(first_plan.source, "update", stale_game, stale_players)
    )

    def call(mutation_id, plan_before, game_payload, player_payload, plan_after):
        return (
            f"public.dice_rating_apply_game_mutation_if_current('{mutation_id}'::uuid, "
            f"{_json_arg(plan_before)}, 'update', {_json_arg(game_payload)}, "
            f"{_json_arg(player_payload)}, {_json_arg(plan_after.source)}, "
            f"{_json_arg(plan_after.player_snapshots)}, {_json_arg(plan_after.profile_states)}, "
            f"'{plan_after.source_digest}', '{plan_after.output_digest}', "
            f"'{game['created_by']}', null, '{original_revision}'::timestamptz)"
        )

    first_call = call(
        "78000000-0000-0000-0000-000000000001",
        source,
        first_game,
        first_players,
        first_plan,
    )
    stale_mutation_id = "78000000-0000-0000-0000-000000000002"
    stale_call = call(
        stale_mutation_id,
        first_plan.source,
        stale_game,
        stale_players,
        stale_plan,
    )
    expected_state = {
        "players": first_plan.player_snapshots,
        "profiles": first_plan.profile_states,
    }
    result = _psql(rf"""
begin;
set local request.jwt.claims = '{{"role":"service_role"}}';
\i {MANUAL_UPDATE_MIGRATION}
do $$
begin
  perform {first_call};
  begin
    perform {stale_call};
    raise exception 'stale update unexpectedly succeeded';
  exception when sqlstate 'P0001' then
    if sqlerrm <> 'dice_game.stale_update' then raise; end if;
  end;
  if public.dice_rating_source_snapshot() is distinct from {_json_arg(first_plan.source)}
     or public.dice_rating_state_snapshot() is distinct from {_json_arg(expected_state)}
     or public.dice_rating_mutation_receipt('{stale_mutation_id}') is not null then
    raise exception 'stale update left partial canonical state or a receipt';
  end if;
end
$$;
rollback;
""")
    assert result.returncode == 0, result.stdout + result.stderr
