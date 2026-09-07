import json
import os
import subprocess
from pathlib import Path

import pytest

from dice.rating_replay import build_rating_plan, project_game_mutation


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "backend/migrations/0064_dice_canonical_rating_only.sql"
PROFILE_INVARIANTS = ROOT / "backend/migrations/0063_dice_canonical_rating_profile_invariants.sql"
ACTIVATION = ROOT / "backend/migrations/0058_dice_canonical_rating_activation.sql"
FILL_FORWARD = ROOT / "backend/migrations/0059_dice_canonical_rating_fill_forward.sql"


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
\i {MIGRATION}
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
\i {MIGRATION}
rollback;
""")
    assert result.returncode != 0
    assert "dice_rating.clean_canonical_state_required" in result.stderr


def test_canonical_only_migration_refuses_missing_cutover_control():
    result = _psql(rf"""
begin;
alter table public.dice_games drop constraint if exists dice_games_live_results_unranked;
drop table if exists public.dice_rating_control;
\i {MIGRATION}
rollback;
""")
    assert result.returncode != 0
    assert "dice_rating.canonical_control_required" in result.stderr


def test_live_materialized_games_reject_manual_update_and_delete():
    result = _psql(rf"""
begin;
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
