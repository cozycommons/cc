import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.dice_test_database import is_isolated_dice_test_database


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = ROOT / "backend" / "migrations" / "0055_dice_canonical_rating_transaction.sql"
DB_URL = os.environ.get("DB_URL")

pytestmark = pytest.mark.skipif(
    not is_isolated_dice_test_database(os.environ),
    reason="requires an allowlisted isolated PostgreSQL database",
)


def _psql(sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["psql", DB_URL, "--no-psqlrc", "--set", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )


def test_canonical_rating_commit_is_atomic_complete_and_service_only():
    sql = rf"""
begin;
\i {CANONICAL_MIGRATION}
set local request.jwt.claims = '{{"role":"service_role"}}';

do $$
declare
  source jsonb;
  player_payload jsonb;
  invalid_player_payload jsonb;
  profile_payload jsonb;
  result jsonb;
  first_game uuid;
begin
  insert into public.dice_games (
    id, created_by, ranked, team1_score, team2_score, winner_team, played_at
  ) values (
    '10000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    false, 21, 10, 1, '2026-01-02T00:00:00Z'
  );
  insert into public.dice_game_players (id, game_id, user_id, team) values
    ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 1),
    ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000002', 1),
    ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000003', 2),
    ('20000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000004', 2);
  insert into public.dice_games (
    id, created_by, ranked, team1_score, team2_score, winner_team, played_at
  ) values (
    '10000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000001',
    true, 10, 10, null, '2026-01-03T00:00:00Z'
  );
  insert into public.dice_game_players (id, game_id, user_id, team) values
    ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 1),
    ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002', 1),
    ('30000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000003', 2),
    ('30000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000004', 2);
  source := public.dice_rating_source_snapshot();

  select coalesce(jsonb_agg(jsonb_build_object(
    'id', player->>'id',
    'elo_before', case when (game->>'ranked')::boolean and game->>'winner_team' is not null then 1500 end,
    'elo_after', case when (game->>'ranked')::boolean and game->>'winner_team' is not null then 1510 end,
    'rating_deviation_before', case when (game->>'ranked')::boolean and game->>'winner_team' is not null then 350 end,
    'rating_deviation_after', case when (game->>'ranked')::boolean and game->>'winner_team' is not null then 297.5 end
  )), '[]'::jsonb)
    into player_payload
    from jsonb_array_elements(source->'players') player
    join jsonb_array_elements(source->'games') game
      on game->>'id' = player->>'game_id';
  select coalesce(jsonb_agg(jsonb_build_object(
    'user_id', value->>'user_id',
    'elo_rating', 1510,
    'rating_deviation', 297.5,
    'ranked_games_played', 1,
    'games_played', 3,
    'wins', 1,
    'losses', 0,
    'ranked_wins', 1,
    'ranked_losses', 0,
    'normal_wins', 0,
    'normal_losses', 0,
    'self_sinks', 0,
    'sinks', 0
  )), '[]'::jsonb)
    into profile_payload
    from jsonb_array_elements(source->'profiles');

  result := public.dice_rating_commit(source, player_payload, profile_payload);
  if (result->>'players_updated')::integer <> jsonb_array_length(source->'players')
     or (result->>'profiles_updated')::integer <> jsonb_array_length(source->'profiles') then
    raise exception 'canonical commit row counts did not match';
  end if;
  if result->'state' is distinct from public.dice_rating_state_snapshot() then
    raise exception 'canonical commit returned a different generation';
  end if;
  if exists (
    select 1 from public.dice_profiles where elo_model_version <> '1.1.0'
  ) then
    raise exception 'canonical commit did not activate model 1.1.0';
  end if;

  invalid_player_payload := (
    select jsonb_agg(jsonb_build_object(
      'id', value->>'id',
      'elo_before', null,
      'elo_after', null,
      'rating_deviation_before', null,
      'rating_deviation_after', null
    )) from jsonb_array_elements(player_payload)
  );
  begin
    perform public.dice_rating_commit(source, invalid_player_payload, profile_payload);
    raise exception 'expected ranked snapshot rejection';
  exception
    when invalid_parameter_value then null;
  end;
  invalid_player_payload := (
    select jsonb_agg(jsonb_build_object(
      'id', value->>'id',
      'elo_before', 1500,
      'elo_after', 1510,
      'rating_deviation_before', 350,
      'rating_deviation_after', 297.5
    )) from jsonb_array_elements(player_payload)
  );
  begin
    perform public.dice_rating_commit(source, invalid_player_payload, profile_payload);
    raise exception 'expected unranked snapshot rejection';
  exception
    when invalid_parameter_value then null;
  end;

  profile_payload := jsonb_set(profile_payload, '{{0,wins}}', '2');
  begin
    perform public.dice_rating_commit(source, player_payload, profile_payload);
    raise exception 'expected contradictory aggregate rejection';
  exception
    when invalid_parameter_value then null;
  end;
  profile_payload := jsonb_set(profile_payload, '{{0,wins}}', '1');

  -- A late profile constraint failure must roll back earlier player updates.
  player_payload := (
    select jsonb_agg(case
      when jsonb_typeof(value->'elo_before') = 'number'
      then jsonb_set(value, '{{elo_before}}', '1700')
      else value
    end)
    from jsonb_array_elements(player_payload)
  );
  profile_payload := jsonb_set(profile_payload, '{{0,rating_deviation}}', '999');
  begin
    perform public.dice_rating_commit(source, player_payload, profile_payload);
    raise exception 'expected deviation constraint failure';
  exception
    when check_violation then null;
  end;
  if exists (select 1 from public.dice_game_players where elo_before is not null and elo_before <> 1500) then
    raise exception 'failed canonical commit leaked partial player updates';
  end if;

  select (value->>'id')::uuid into first_game
  from jsonb_array_elements(source->'games') limit 1;
  update public.dice_games set ranked = not ranked where id = first_game;
  begin
    perform public.dice_rating_commit(source, player_payload, profile_payload);
    raise exception 'expected stale source rejection';
  exception
    when serialization_failure then null;
  end;
end
$$;

do $$
begin
  if pg_catalog.has_function_privilege(
    'anon', 'public.dice_rating_commit(jsonb,jsonb,jsonb)', 'execute'
  ) or pg_catalog.has_function_privilege(
    'authenticated', 'public.dice_rating_commit(jsonb,jsonb,jsonb)', 'execute'
  ) or pg_catalog.has_function_privilege(
    'anon', 'public.dice_rating_source_snapshot()', 'execute'
  ) or pg_catalog.has_function_privilege(
    'authenticated', 'public.dice_rating_state_snapshot()', 'execute'
  ) then
    raise exception 'canonical rating RPC is exposed outside service_role';
  end if;
end
$$;
rollback;
"""
    result = _psql(sql)
    assert result.returncode == 0, result.stdout + result.stderr


def test_canonical_rating_commit_rechecks_source_after_waiting_for_writer():
    migration = subprocess.run(
        [
            "psql", DB_URL, "--no-psqlrc", "--set", "ON_ERROR_STOP=1",
            "--single-transaction", "--file", str(CANONICAL_MIGRATION),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migration.returncode == 0, migration.stdout + migration.stderr
    captured = subprocess.run(
        [
            "psql", DB_URL, "--no-psqlrc", "--tuples-only", "--no-align",
            "--set", "ON_ERROR_STOP=1",
        ],
        cwd=ROOT,
        input="""
set request.jwt.claims = '{"role":"service_role"}';
select jsonb_build_object(
  'source', public.dice_rating_source_snapshot(),
  'state', public.dice_rating_state_snapshot()
)::text;
""",
        capture_output=True,
        text=True,
        check=False,
    )
    assert captured.returncode == 0, captured.stdout + captured.stderr
    payload = json.loads(captured.stdout.strip().splitlines()[-1])
    game = payload["source"]["games"][0]

    writer = subprocess.Popen(
        ["psql", DB_URL, "--no-psqlrc", "--set", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert writer.stdin is not None
    writer.stdin.write(f"""
begin;
update public.dice_games set ranked = not ranked where id = '{game['id']}'::uuid;
select pg_sleep(1);
commit;
""")
    writer.stdin.close()
    time.sleep(0.2)

    def json_arg(value):
        return "$payload$" + json.dumps(value, separators=(",", ":")) + "$payload$::jsonb"

    commit = _psql(f"""
set request.jwt.claims = '{{"role":"service_role"}}';
select public.dice_rating_commit(
  {json_arg(payload['source'])},
  {json_arg(payload['state']['players'])},
  {json_arg(payload['state']['profiles'])}
);
""")
    writer.wait(timeout=5)
    writer_stderr = writer.stderr.read() if writer.stderr is not None else ""
    try:
        assert writer.returncode == 0, writer_stderr
        assert commit.returncode != 0
        assert "dice_rating.source_changed" in commit.stderr
    finally:
        restore = _psql(
            "update public.dice_games set ranked = "
            f"{'true' if game['ranked'] else 'false'} where id = '{game['id']}'::uuid;"
        )
        assert restore.returncode == 0, restore.stdout + restore.stderr
