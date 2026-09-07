"""Contract and loopback integration tests for the Virtual Dice ledger."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "backend/migrations/0048_dice_virtual_currency.sql"
LOCAL_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
TOURNAMENT = "30000000-0000-0000-0000-000000000001"
PLAYER = "10000000-0000-0000-0000-000000000002"
CREATOR = "10000000-0000-0000-0000-000000000001"


def _sql(sql: str) -> str:
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "--quiet", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def _service(sql: str) -> str:
    return _sql("set request.jwt.claims = '{\"role\":\"service_role\"}';\n" + sql)


def _fails(sql: str) -> str:
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    return result.stderr


def test_migration_is_private_append_only_and_tournament_scoped():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ("dice_virtual_markets", "dice_virtual_picks", "dice_virtual_ledger"):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    assert "unique (tournament_id, user_id, operation_key)" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "potential_return integer not null" in sql
    assert "settlement_reversal" in sql
    assert "before update or delete on public.dice_virtual_ledger" in sql
    assert "before update on public.dice_virtual_picks" in sql


def test_virtual_currency_schema_is_private_on_loopback():
    if os.environ.get("DB_URL") != LOCAL_DB_URL:
        pytest.skip("requires the locked local Dice database")
    assert _sql("select has_table_privilege('anon', 'dice_virtual_ledger', 'select');") == "f"
    assert _sql("select has_table_privilege('authenticated', 'dice_virtual_picks', 'insert');") == "f"
    assert _sql("select has_function_privilege('anon', 'dice_virtual_place_pick(uuid,bigint,uuid,text,text,integer)', 'execute');") == "f"
    assert _sql("select has_function_privilege('service_role', 'dice_virtual_settle_market(bigint,text)', 'execute');") == "t"


@pytest.fixture
def market_id():
    if os.environ.get("DB_URL") != LOCAL_DB_URL:
        pytest.skip("requires the locked local Dice database")
    _sql("truncate public.dice_virtual_ledger, public.dice_virtual_picks, public.dice_virtual_markets restart identity;")
    match_id = str(uuid.uuid4())
    market = _sql(f"""
      insert into public.dice_live_matches
        (id, created_by, team_order, teams, rules_snapshot)
      values ('{match_id}', '{CREATOR}', '["blue","clay"]',
        '{{"blue":["{PLAYER}"],"clay":["10000000-0000-0000-0000-000000000003"]}}', '{{}}');
      insert into public.dice_virtual_markets
        (tournament_id, live_match_id, model_id, model_version, match_version, selections)
      values ('{TOURNAMENT}', '{match_id}', 'elo-score-composition', '1.0.0', 0,
        '{{"blue":{{"probability_millionths":600000}},"clay":{{"probability_millionths":400000}}}}')
      returning id;
    """)
    yield int(market)


def test_atomic_pick_retry_settlement_and_correction(market_id):
    assert _service(f"select dice_virtual_open_bankroll('{TOURNAMENT}', '{PLAYER}', 1000);") == "1000"
    pick_sql = (
        f"select dice_virtual_place_pick('{TOURNAMENT}', {market_id}, '{PLAYER}', "
        "'mobile-1', 'blue', 300)::text;"
    )
    first = json.loads(_service(pick_sql))
    retry = json.loads(_service(pick_sql))
    assert first["id"] == retry["id"]
    assert first["potential_return"] == 500
    assert "dice_virtual.quote_terms_immutable" in _fails(
        f"update dice_virtual_picks set potential_return=999 where id={first['id']};"
    )
    assert "dice_virtual.ledger_append_only" in _fails(
        f"update dice_virtual_ledger set amount=-1 where pick_id={first['id']};"
    )
    assert _sql(f"select sum(amount) from dice_virtual_ledger where tournament_id='{TOURNAMENT}' and user_id='{PLAYER}';") == "700"

    _service(f"select dice_virtual_settle_market({market_id}, 'blue');")
    _service(f"select dice_virtual_settle_market({market_id}, 'blue');")
    assert _sql(f"select sum(amount) from dice_virtual_ledger where tournament_id='{TOURNAMENT}' and user_id='{PLAYER}';") == "1200"
    assert _sql(f"select settlement_revision from dice_virtual_markets where id={market_id};") == "1"

    _service(f"select dice_virtual_settle_market({market_id}, null);")
    assert _sql(f"select sum(amount) from dice_virtual_ledger where tournament_id='{TOURNAMENT}' and user_id='{PLAYER}';") == "1000"
    assert _sql(f"select status from dice_virtual_picks where id={first['id']};") == "void"
    assert _sql(f"select settlement_revision from dice_virtual_markets where id={market_id};") == "2"

    _service(f"select dice_virtual_settle_market({market_id}, 'clay');")
    assert _sql(f"select sum(amount) from dice_virtual_ledger where tournament_id='{TOURNAMENT}' and user_id='{PLAYER}';") == "700"
    assert _sql(f"select status from dice_virtual_picks where id={first['id']};") == "lost"
    assert _sql(f"select settlement_revision from dice_virtual_markets where id={market_id};") == "3"


def test_authenticated_role_cannot_call_mutation_rpc(market_id):
    result = subprocess.run(
        ["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c",
         f"set request.jwt.claims = '{{\"role\":\"authenticated\"}}'; select dice_virtual_open_bankroll('{TOURNAMENT}', '{PLAYER}', 1000);"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "dice_virtual.service_role_required" in result.stderr


def test_concurrent_picks_cannot_overdraw_bankroll(market_id):
    _service(f"select dice_virtual_open_bankroll('{TOURNAMENT}', '{PLAYER}', 1000);")
    commands = []
    for client_id in ("concurrent-a", "concurrent-b"):
        sql = (
            "set request.jwt.claims = '{\"role\":\"service_role\"}'; "
            f"select dice_virtual_place_pick('{TOURNAMENT}', {market_id}, '{PLAYER}', "
            f"'{client_id}', 'blue', 800);"
        )
        commands.append(["psql", os.environ["DB_URL"], "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", sql])
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in commands]
    results = [(*process.communicate(), process.returncode) for process in processes]

    assert sum(code == 0 for _out, _err, code in results) == 1, results
    assert sum("dice_virtual.insufficient_balance" in err for _out, err, _code in results) == 1
    assert _sql(f"select sum(amount) from dice_virtual_ledger where tournament_id='{TOURNAMENT}' and user_id='{PLAYER}';") == "200"
