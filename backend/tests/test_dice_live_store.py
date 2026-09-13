"""Contract and loopback integration tests for the private live store."""

import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest
from tests.dice_test_database import is_isolated_dice_test_database
from supabase import create_client


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "backend/migrations/0044_dice_live_store.sql"
AUTH_CLAIMS_MIGRATION = ROOT / "backend/migrations/0046_dice_live_rpc_auth_claims.sql"
METRICS_MIGRATION = ROOT / "backend/migrations/0065_dice_live_command_metrics.sql"
LOCAL_API_URL = "http://127.0.0.1:54321"
if is_isolated_dice_test_database(os.environ) and os.environ.get("DICE_TEST_REST_URL") == "http://127.0.0.1:55431":
    LOCAL_API_URL = "http://127.0.0.1:55431"
REFEREE = "10000000-0000-0000-0000-000000000001"
OTHER_REFEREE = "10000000-0000-0000-0000-000000000002"


def _sql(sql: str, *, db_url: str | None = None) -> str:
    environment = {**os.environ, "PGOPTIONS": "-c statement_timeout=10000"}
    result = subprocess.run(["psql", db_url or os.environ["DB_URL"], "--no-psqlrc", "--tuples-only", "--no-align", "-v", "ON_ERROR_STOP=1", "-c", sql], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip().splitlines()[-1]


def _append_sql(
    match_id: str,
    command_id: str,
    event_id: str,
    expected: int = 0,
    claim_role: str = "service_role",
) -> str:
    event = {
        "id": event_id,
        "kind": "observation",
        "thrower_id": "10000000-0000-0000-0000-000000000001",
        "throwing_team_id": "team1",
        "outcome": "point",
        "score_delta": [1, 0],
        "match_elapsed_ms": 1000,
    }
    projection = {"score": [1, 0], "status": "active", "termination_reason": None, "coverage": "complete", "observations": 1, "stats": {"point": 1}}
    return f"""
      set request.jwt.claims = '{{"role":"{claim_role}"}}';
      select public.dice_live_append_command(
        '{match_id}'::uuid, '{REFEREE}'::uuid, '{command_id}', {expected},
        '{json.dumps({'kind': 'record_throw', 'event': event}, separators=(',', ':'))}'::jsonb,
        '{json.dumps([event], separators=(',', ':'))}'::jsonb,
        '{json.dumps(projection, separators=(',', ':'))}'::jsonb,
        array[1, 0]::smallint[], 'active', 'complete'
      )::text;
    """


def _append_payload(match_id: str, command_id: str, event_id: str) -> dict:
    event = {
        "id": event_id,
        "kind": "observation",
        "thrower_id": REFEREE,
        "throwing_team_id": "team1",
        "outcome": "point",
        "score_delta": [1, 0],
        "match_elapsed_ms": 1000,
    }
    projection = {
        "score": [1, 0],
        "status": "active",
        "termination_reason": None,
        "coverage": "complete",
        "observations": 1,
        "stats": {"point": 1},
    }
    return {
        "p_match_id": match_id,
        "p_recorded_by": REFEREE,
        "p_client_command_id": command_id,
        "p_expected_version": 0,
        "p_canonical_payload": {"kind": "record_throw", "event": event},
        "p_events": [event],
        "p_projection": projection,
        "p_score": [1, 0],
        "p_status": "active",
        "p_detail_coverage": "complete",
    }


def _rpc(payload: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{os.environ['API_URL']}/rest/v1/rpc/dice_live_append_command",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "apikey": token,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_migration_keeps_the_live_store_private_and_ledger_append_only():
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in ("dice_live_matches", "dice_live_referees", "dice_live_commands", "dice_live_events"):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"public.{table}" in sql
    assert "revoke all on table public.dice_live_matches, public.dice_live_referees" in sql
    assert "to service_role" in sql
    assert "unique (match_id, recorded_by, client_command_id)" in sql
    assert "unique (match_id, sequence)" in sql
    assert "unique (match_id, match_version, command_index)" in sql
    assert "before update or delete on public.dice_live_events" in sql
    assert "identity check deliberately precedes the version check" in sql
    assert "update public.dice_live_events" not in sql
    assert "delete from public.dice_live_events" not in sql


def test_auth_claims_forward_migration_preserves_service_role_only_boundary():
    sql = AUTH_CLAIMS_MIGRATION.read_text(encoding="utf-8")

    assert "current_setting('request.jwt.claims', true)" in sql
    assert "->> 'role'" in sql
    assert "<> 'service_role'" in sql
    assert "set_config('request.jwt.claim.role', 'service_role', true)" in sql
    assert ") from public, anon, authenticated;" in sql
    assert ") to service_role;" in sql


def test_command_metrics_migration_is_private_and_deduplicated():
    sql = METRICS_MIGRATION.read_text(encoding="utf-8")

    assert "create table public.dice_live_command_metrics" in sql
    assert "unique (match_id, referee_id, operation_id)" in sql
    assert "alter table public.dice_live_command_metrics enable row level security" in sql
    assert "revoke all on table public.dice_live_command_metrics from public, anon, authenticated" in sql
    assert "grant all on table public.dice_live_command_metrics to service_role" in sql


def test_live_store_schema_and_function_are_installed_on_loopback():
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip("requires an explicitly isolated Dice test database")

    tables = _sql("""
      select string_agg(table_name, ',' order by table_name)
        from information_schema.tables
       where table_schema = 'public'
         and table_name like 'dice_live_%';
    """)
    assert tables == "dice_live_command_metrics,dice_live_commands,dice_live_events,dice_live_matches,dice_live_rating_repairs,dice_live_referees"
    assert _sql("select has_table_privilege('anon', 'public.dice_live_events', 'insert');") == "f"
    assert _sql("select has_table_privilege('authenticated', 'public.dice_live_matches', 'select');") == "f"
    assert _sql("select has_table_privilege('authenticated', 'public.dice_live_command_metrics', 'insert');") == "f"
    assert _sql("select has_function_privilege('anon', 'public.dice_live_append_command(uuid,uuid,text,integer,jsonb,jsonb,jsonb,smallint[],text,text)', 'execute');") == "f"


@pytest.fixture
def live_match():
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip("requires an explicitly isolated Dice test database")
    match_id = str(uuid.uuid4())
    _sql(f"""
      insert into public.dice_live_matches
        (id, created_by, team_order, teams, rules_snapshot)
      values (
        '{match_id}', '{REFEREE}', '["team1","team2"]'::jsonb,
        '{{"team1":["{REFEREE}"],"team2":["{OTHER_REFEREE}"]}}'::jsonb,
        '{{"contract_version":1,"ruleset_version":1,"scoring_version":1,
          "target_score":5,"win_by":1,"call_policy":{{
          "low_call_deadline":"before_surface_contact","low_call_exceptions":[],
          "short_boundary":"center_line_is_short","midline_remedy":"consume_attempt",
          "dispute_authority":"teams_or_designated_referee","uncertain_call_remedy":"retoss"
        }}}}'::jsonb
      );
      insert into public.dice_live_referees (match_id, user_id) values ('{match_id}', '{REFEREE}');
    """)
    yield match_id


def test_exact_retry_returns_the_same_receipt_and_different_payload_conflicts(live_match):
    command_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    first = _sql(_append_sql(live_match, command_id, event_id))
    retry = _sql(_append_sql(live_match, command_id, event_id))
    assert json.loads(first) == json.loads(retry)
    assert _sql(f"select count(*) from public.dice_live_events where match_id = '{live_match}';") == "1"

    different = _append_sql(live_match, command_id, str(uuid.uuid4())).replace("record_throw", "retoss")
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", different],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "dice_live.command_id_conflict" in result.stderr
    assert _sql(f"select count(*) from public.dice_live_events where match_id = '{live_match}';") == "1"


def test_service_role_rest_rpc_accepts_modern_jwt_claims(live_match):
    if os.environ.get("API_URL") != LOCAL_API_URL or not os.environ.get("SECRET_KEY"):
        pytest.skip("requires the locked local Dice REST API")

    payload = _append_payload(live_match, str(uuid.uuid4()), str(uuid.uuid4()))
    status, receipt = _rpc(payload, os.environ["SECRET_KEY"])

    assert status == 200, receipt
    assert receipt["accepted_version"] == 1
    assert receipt["projection"]["score"] == [1, 0]
    assert _sql(f"select count(*) from public.dice_live_events where match_id = '{live_match}';") == "1"


def test_service_role_postgrest_upsert_deduplicates_command_metrics(live_match):
    if os.environ.get("API_URL") != LOCAL_API_URL or not os.environ.get("SECRET_KEY"):
        pytest.skip("requires the locked local Dice REST API")

    operation_id = str(uuid.uuid4())
    row = {
        "operation_id": operation_id,
        "match_id": live_match,
        "referee_id": REFEREE,
        "attempts": 2,
        "winner": "hedge",
        "outcome": "resolved",
        "status": 200,
        "duration_ms": 900,
        "hedge_delay_ms": 800,
        "loser_cancelled": True,
    }
    client = create_client(os.environ["API_URL"], os.environ["SECRET_KEY"])
    client.table("dice_live_command_metrics").upsert(
        row, on_conflict="match_id,referee_id,operation_id"
    ).execute()
    client.table("dice_live_command_metrics").upsert(
        {**row, "duration_ms": 850},
        on_conflict="match_id,referee_id,operation_id",
    ).execute()

    assert _sql(
        f"select count(*) || ':' || min(duration_ms) "
        f"from public.dice_live_command_metrics where operation_id = '{operation_id}';"
    ) == "1:850"


def test_authenticated_claim_cannot_cross_the_service_role_rpc_boundary(live_match):
    sql = "set role service_role;\n" + _append_sql(
        live_match,
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        claim_role="authenticated",
    )
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "dice_live.service_role_required" in result.stderr
    assert _sql(f"select count(*) from public.dice_live_events where match_id = '{live_match}';") == "0"


def test_two_writers_from_one_version_have_one_winner_and_one_stale_conflict(live_match):
    commands = [
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", _append_sql(live_match, str(uuid.uuid4()), str(uuid.uuid4()))],
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", _append_sql(live_match, str(uuid.uuid4()), str(uuid.uuid4()))],
    ]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in commands]
    results = [(out, err, process.returncode) for process in processes for out, err in [process.communicate()]]
    successes = [output for output, _error, code in results if code == 0]
    failures = [error for _output, error, code in results if code != 0]
    assert len(successes) == 1, results
    assert len(failures) == 1, results
    assert "dice_live.stale_version" in failures[0]
    assert _sql(f"select version::text from public.dice_live_matches where id = '{live_match}';") == "1"
    assert _sql(f"select count(*) from public.dice_live_events where match_id = '{live_match}';") == "1"
