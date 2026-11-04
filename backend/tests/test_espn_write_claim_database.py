"""Real PostgreSQL claims; synthetic disposable databases, no ESPN calls.

CI uses its existing isolated DB_URL. Local Supabase runs may explicitly set
ESPN_WRITE_TEST_DB_URL to 127.0.0.1:55322/espn_write_test_<name>. Never load dotenv.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
import subprocess
import time
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest

import migration_runner
from tests.dice_test_database import is_isolated_dice_test_database
from tests.migration_harness import MigrationDatabase, REPO


ROSTER = "espn_roster_edits"
TRADE = "espn_trade_proposals"
ACCOUNT = "11111111-1111-1111-1111-111111111111"
OTHER_ACCOUNT = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="module")
def claim_database():
    url = os.environ.get("ESPN_WRITE_TEST_DB_URL", "")
    parsed = urlparse(url)
    local = (parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
             and parsed.port == 55322 and parsed.path.startswith("/espn_write_test_")
             and not parsed.query and not parsed.fragment)
    if not local:
        if not is_isolated_dice_test_database(os.environ):
            # The existing hosted backend job already requires its isolated DB.
            if any(os.environ.get(flag) == "1" for flag in (
                "ESPN_REQUIRE_DATABASE_TESTS", "DICE_REQUIRE_DATABASE_TESTS"
            )):
                pytest.fail("Required ESPN claims need an allowlisted isolated database")
            pytest.skip("allowlisted isolated database required for ESPN claim tests")
        url = os.environ["DB_URL"]
        parsed = urlparse(url)
    admin = MigrationDatabase(url)
    name = "espn_write_test_" + uuid4().hex
    admin.sql(f'CREATE DATABASE "{name}";')
    database = MigrationDatabase(urlunparse(parsed._replace(path="/" + name)))
    try:
        database.sql((REPO / "scripts/supabase-test-scaffold.sql").read_text())
        database.sql(migration_runner.render(["beli"]))
        yield database
    finally:
        admin.sql(f'DROP DATABASE "{name}" WITH (FORCE);')


@pytest.fixture
def db(claim_database):
    claim_database.sql(f"""TRUNCATE public.{ROSTER}, public.{TRADE}, public.espn_accounts CASCADE;
        INSERT INTO public.espn_accounts
        (id,league_id,season,espn_s2_enc,swid_enc,token_hash,token_prefix) VALUES
        ('{ACCOUNT}',123,2027,'synthetic','synthetic','synthetic-one','test'),
        ('{OTHER_ACCOUNT}',123,2027,'synthetic','synthetic','synthetic-two','test');""")
    return claim_database


def proposal(db, table, *, players=(101, 202), account=ACCOUNT, league=123,
             season=2027, status="pending", string_ids=False):
    identity = str(uuid4())
    if table == ROSTER:
        columns = "add_player_id,drop_player_id"
        values = ",".join("NULL" if p is None else str(p) for p in players)
    else:
        columns = "counterparty_team_id,give_player_ids,receive_player_ids"
        arrays = [[str(p) if string_ids else p] if p is not None else [] for p in players]
        values = "2," + ",".join("'" + json.dumps(a) + "'::jsonb" for a in arrays)
    db.sql(f"""SET ROLE service_role;
        INSERT INTO public.{table}
        (id,account_id,league_id,season,team_id,preview,expires_at,status,{columns})
        VALUES ('{identity}','{account}',{league},{season},1,'synthetic',now()+interval '1 hour',
                '{status}',{values});""")
    return identity


def claim(table, identity):
    return (f"UPDATE public.{table} SET status='executing' "
            f"WHERE id='{identity}' AND status='pending' RETURNING id;")


@contextmanager
def session(db, name):
    process = subprocess.Popen(
        ["psql", db.url, "-XAtq", "-v", "ON_ERROR_STOP=1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    def command(sql):
        marker = "done_" + uuid4().hex
        process.stdin.write(sql + "\n\\echo " + marker + "\n")
        process.stdin.flush()
        lines = []
        for line in process.stdout:
            if line.strip() == marker:
                return "".join(lines).strip()
            lines.append(line)
        raise AssertionError("psql exited: " + "".join(lines))

    try:
        command(f"SET application_name='{name}'; SET statement_timeout='8s'; SET ROLE service_role;")
        yield command
    finally:
        process.stdin.close()
        process.wait(timeout=12)
        process.stdout.close()


def wait_blocked(db, name, result):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        blocked = db.sql(f"""SELECT count(*) FROM pg_catalog.pg_locks l
            JOIN pg_catalog.pg_stat_activity a ON a.pid=l.pid
            WHERE a.application_name='{name}' AND NOT l.granted AND l.locktype='advisory';""").stdout.strip()
        if blocked == "1":
            return
        if result.done():
            pytest.fail("second claim returned while first claim was uncommitted: " + result.result())
        time.sleep(0.03)
    pytest.fail("second claim did not wait on the account advisory transaction lock")


@pytest.mark.parametrize("first_table,second_table", [
    (ROSTER, ROSTER), (TRADE, TRADE), (ROSTER, TRADE), (TRADE, ROSTER),
])
@pytest.mark.parametrize("rollback", [False, True])
def test_simultaneous_overlapping_claims(db, first_table, second_table, rollback):
    first = proposal(db, first_table)
    second = proposal(db, second_table, string_ids=True)
    # Both request prechecks finish before either claims. Separate PostgreSQL
    # sessions reproduce multiworker requests, including the outer UPDATE's old
    # statement snapshot while its trigger waits for the first transaction.
    for table in (ROSTER, TRADE):
        assert db.sql(f"SELECT count(*) FROM public.{table} WHERE status IN ('executing','unknown','uncertain');").stdout.strip() == "0"
    name = "espn_claim_" + uuid4().hex
    with session(db, "espn_first") as one, session(db, name) as two:
        assert one("BEGIN; " + claim(first_table, first)) == first
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(two, claim(second_table, second))
            try:
                wait_blocked(db, name, result)
            finally:
                one("ROLLBACK;" if rollback else "COMMIT;")
            assert result.result(timeout=10) == (second if rollback else "")
    expected = "pending" if rollback else "executing"
    assert db.sql(f"SELECT status FROM public.{first_table} WHERE id='{first}';").stdout.strip() == expected
    expected = "executing" if rollback else "pending"
    assert db.sql(f"SELECT status FROM public.{second_table} WHERE id='{second}';").stdout.strip() == expected


@pytest.mark.parametrize("first_table,second_table", [(ROSTER, TRADE), (TRADE, ROSTER)])
@pytest.mark.parametrize("status", ["unknown", "uncertain"])
def test_unknown_outcome_committed_after_precheck_blocks_claim(db, first_table, second_table, status):
    first = proposal(db, first_table, string_ids=True)
    second = proposal(db, second_table)
    name = "espn_outcome_" + uuid4().hex
    with session(db, "espn_first") as one, session(db, name) as two:
        assert one("BEGIN; " + claim(first_table, first)) == first
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(two, claim(second_table, second))
            try:
                wait_blocked(db, name, result)
            finally:
                one(f"UPDATE public.{first_table} SET status='{status}' WHERE id='{first}'; COMMIT;")
            assert result.result(timeout=10) == ""


@pytest.mark.parametrize("scope", ["players", "league", "season", "account"])
def test_simultaneous_unrelated_claims_allowed(db, scope):
    first = proposal(db, ROSTER)
    kwargs = {"players": (303, 404)} if scope == "players" else {
        "league": {"league": 456}, "season": {"season": 2028},
        "account": {"account": OTHER_ACCOUNT},
    }[scope]
    second = proposal(db, TRADE, **kwargs)
    name = "espn_unrelated_" + uuid4().hex
    with session(db, "espn_first") as one, session(db, name) as two:
        assert one("BEGIN; " + claim(ROSTER, first)) == first
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(two, claim(TRADE, second))
            try:
                if scope == "account":
                    assert result.result(timeout=5) == second
                else:
                    wait_blocked(db, name, result)
            finally:
                one("COMMIT;")
            assert result.result(timeout=10) == second


@pytest.mark.parametrize("old_table,new_table", [(ROSTER, ROSTER), (TRADE, TRADE), (ROSTER, TRADE), (TRADE, ROSTER)])
@pytest.mark.parametrize("old_status", ["executing", "unknown", "uncertain"])
def test_all_unresolved_statuses_and_string_ids_block(db, old_table, new_table, old_status):
    proposal(db, old_table, players=(None, 202), status=old_status, string_ids=True)
    identity = proposal(db, new_table, players=(202, None), string_ids=True)
    assert db.sql("SET ROLE service_role; " + claim(new_table, identity)).stdout.strip() == ""


@pytest.mark.parametrize("table", [ROSTER, TRADE])
def test_empty_player_lists_and_null_roster_sides_are_safe(db, table):
    proposal(db, table, players=(None, None), status="unknown")
    identity = proposal(db, table, players=(101, None))
    assert db.sql("SET ROLE service_role; " + claim(table, identity)).stdout.strip() == identity


@pytest.mark.parametrize("table", [ROSTER, TRADE])
def test_every_transition_into_executing_is_guarded_and_resolution_is_unaffected(db, table):
    blocker = proposal(db, ROSTER, status="unknown")
    identity = proposal(db, table, status="uncertain")
    result = db.sql(f"SET ROLE service_role; UPDATE public.{table} SET status='executing' WHERE id='{identity}' RETURNING id;")
    assert result.stdout.strip() == ""
    db.sql(f"SET ROLE service_role; UPDATE public.{ROSTER} SET status='failed' WHERE id='{blocker}';")
    # Excludes itself even if currently unresolved. Leaving executing must work
    # at any isolation level (only entering executing requires a fresh snapshot).
    assert db.sql(f"SET ROLE service_role; UPDATE public.{table} SET status='executing' WHERE id='{identity}' RETURNING id;").stdout.strip() == identity
    assert db.sql(f"BEGIN ISOLATION LEVEL REPEATABLE READ; SET ROLE service_role; UPDATE public.{table} SET status='unknown' WHERE id='{identity}' RETURNING id; COMMIT;").stdout.strip() == identity


@pytest.mark.parametrize("table", [ROSTER, TRADE])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "READ UNCOMMITTED"])
def test_claim_fails_closed_outside_read_committed(db, table, isolation):
    identity = proposal(db, table)
    result = db.sql(f"BEGIN ISOLATION LEVEL {isolation}; SET ROLE service_role; " + claim(table, identity), check=False)
    assert result.returncode != 0
    assert "ESPN write claims require READ COMMITTED isolation" in result.stderr
    assert db.sql(f"SELECT status FROM public.{table} WHERE id='{identity}';").stdout.strip() == "pending"


@pytest.mark.parametrize("table", [ROSTER, TRADE])
@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_only_backend_role_can_read_or_claim(db, table, role):
    identity = proposal(db, table)
    for statement in (f"SELECT * FROM public.{table};", claim(table, identity)):
        result = db.sql(f"SET ROLE {role}; " + statement, check=False)
        assert result.returncode != 0 and "permission denied" in result.stderr
    assert db.sql("SELECT rolbypassrls FROM pg_catalog.pg_roles WHERE rolname='service_role';").stdout.strip() == "t"
    assert db.sql("SET ROLE service_role; " + claim(table, identity)).stdout.strip() == identity


@pytest.mark.parametrize("tamper", [
    f"ALTER TABLE public.{ROSTER} DISABLE TRIGGER espn_write_claim_guard;",
    f"DROP TRIGGER espn_write_claim_guard ON public.{TRADE};",
    "ALTER FUNCTION public.espn_write_claim_guard() SECURITY DEFINER;",
    "ALTER FUNCTION public.espn_write_claim_guard() STABLE;",
    "ALTER FUNCTION public.espn_write_claim_guard() SET search_path=public;",
    "DROP FUNCTION public.espn_write_claim_guard() CASCADE;",
    "GRANT EXECUTE ON FUNCTION public.espn_write_claim_guard() TO PUBLIC;",
    f"GRANT UPDATE ON public.{ROSTER} TO authenticated;",
    f"GRANT UPDATE (status) ON public.{TRADE} TO authenticated;",
    f"ALTER TABLE public.{TRADE} DISABLE ROW LEVEL SECURITY;",
])
def test_release_contract_rejects_unsafe_guard(db, tamper):
    contract = (REPO / "backend/migrations/beli_schema_contract.sql").read_text()
    db.sql(contract)
    result = db.sql("BEGIN; " + tamper + "\n" + contract, check=False)
    assert result.returncode != 0 and "Beli schema contract:" in result.stderr
    db.sql(contract)  # Failed psql connection rolled the tampering back.


def test_schema_receipt_and_replay_are_safe(db):
    assert db.sql("SELECT max(version) FROM public.beli_schema_migrations;").stdout.strip() == "90"
    assert "Applying " not in db.sql(migration_runner.render(["beli"])).stdout


@pytest.mark.parametrize("required_flag", ["ESPN_REQUIRE_DATABASE_TESTS", "DICE_REQUIRE_DATABASE_TESTS"])
def test_required_database_suite_cannot_silently_skip(monkeypatch, required_flag):
    monkeypatch.delenv("ESPN_WRITE_TEST_DB_URL", raising=False)
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.delenv("ESPN_REQUIRE_DATABASE_TESTS", raising=False)
    monkeypatch.delenv("DICE_REQUIRE_DATABASE_TESTS", raising=False)
    monkeypatch.setenv(required_flag, "1")
    with pytest.raises(pytest.fail.Exception, match="allowlisted isolated database"):
        try:
            next(claim_database.__wrapped__())
        except pytest.skip.Exception as error:
            raise AssertionError("Required database suite silently skipped") from error
