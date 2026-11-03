"""Exercise release migrations and RLS on owned, disposable PostgreSQL databases."""
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest

import migration_runner
from tests.dice_test_database import is_isolated_dice_test_database


@pytest.fixture
def trips_database():
    if not is_isolated_dice_test_database(os.environ):
        if os.environ.get('DICE_REQUIRE_DATABASE_TESTS') == '1':
            pytest.fail('Trips migration tests require the isolated CI database.')
        pytest.skip('An isolated loopback test database is required.')
    admin_url = os.environ['DB_URL']
    name = f'cc_trips_{os.getpid()}_{uuid4().hex[:8]}'
    url = urlunparse(urlparse(admin_url)._replace(path=f'/{name}'))

    def sql(query, target=url):
        return subprocess.run(['psql', target, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1'],
                              input=query, text=True, capture_output=True)

    created = sql(f'create database "{name}";', admin_url)
    assert created.returncode == 0, created.stderr
    try:
        scaffold = Path(__file__).resolve().parents[2] / 'scripts/supabase-test-scaffold.sql'
        result = sql(scaffold.read_text())
        assert result.returncode == 0, result.stderr
        yield sql
    finally:
        result = sql(f'drop database "{name}" with (force);', admin_url)
        assert result.returncode == 0, result.stderr


def apply(sql):
    result = sql(migration_runner.render(['trips']))
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def seed(sql):
    result = sql("""
      insert into auth.users(id) values
        ('00000000-0000-0000-0000-000000000001'),
        ('00000000-0000-0000-0000-000000000002');
      insert into trips_groups(id, owner_id, member_user_ids, data) values (
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000001',
        array['00000000-0000-0000-0000-000000000001'::uuid],
        '{"name":"Migration preservation test","expenses":[]}'
      );
    """)
    assert result.returncode == 0, result.stderr


def test_fresh_install_repeat_and_service_role_attestation(trips_database):
    sql = trips_database
    apply(sql)
    seed(sql)
    second = apply(sql)
    assert 'Applying ' not in second.stdout
    assert sql('select data->>\'name\' from trips_groups;').stdout.strip() == 'Migration preservation test'
    result = sql('set role service_role; select public.trips_release_readiness();')
    assert result.returncode == 0 and result.stdout.strip().endswith('t'), result.stderr
    for role in ('anon', 'authenticated'):
        result = sql(f'set role {role}; select public.trips_release_readiness();')
        assert result.returncode != 0 and 'permission denied' in result.stderr


def test_upgrade_from_original_ledger_preserves_data_and_receipts(trips_database):
    sql = trips_database
    original = migration_runner.ROOT / 'trips/migrations/0001_trips_ledger.sql'
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    result = sql(original.read_text() + f"""
      create table trips_schema_migrations(
        version integer primary key, applied_at timestamptz not null default now(), checksum text
      );
      insert into trips_schema_migrations(version, checksum) values (1, '{digest}');
    """)
    assert result.returncode == 0, result.stderr
    seed(sql)
    upgraded = apply(sql)
    assert 'Applying 0001' not in upgraded.stdout
    assert 'Applying 0002_trips_release_readiness' in upgraded.stdout
    assert sql('select count(*) from trips_groups;').stdout.strip() == '1'
    assert sql('select count(*) from trips_schema_migrations;').stdout.strip() == '3'


@pytest.mark.parametrize('damage, expected', [
    ('alter table trips_groups disable row level security;', 'RLS is disabled'),
    ('alter table trips_groups rename column data to missing_data;', 'missing or nullable column data'),
    ('grant update on trips_groups to authenticated;', 'unsafe ledger grants'),
    ('grant select on trips_groups to anon;', 'required ledger grants changed'),
    ('drop policy trips_member_read on trips_groups;', 'member read policy changed'),
    ('alter policy trips_member_read on trips_groups using (true);', 'member read policy changed'),
    ('drop index trips_groups_members;', 'membership index missing'),
])
def test_readiness_rejects_schema_and_security_drift(trips_database, damage, expected):
    sql = trips_database
    apply(sql)
    assert sql(damage).returncode == 0
    result = sql('select trips_release_readiness();')
    assert result.returncode != 0 and expected in result.stderr


def test_receipt_corruption_and_untracked_existing_schema_fail_closed(trips_database):
    sql = trips_database
    apply(sql)
    assert sql("update trips_schema_migrations set checksum='corrupt' where version=1;").returncode == 0
    result = sql(migration_runner.render(['trips']))
    assert result.returncode != 0 and 'Migration checksum changed' in result.stderr
    assert 'Applying ' not in result.stdout
    assert sql('drop table trips_schema_migrations;').returncode == 0
    result = sql(migration_runner.render(['trips']))
    assert result.returncode != 0 and 'no migration history' in result.stderr


def test_member_rls_and_browser_write_denial_on_real_database(trips_database):
    sql = trips_database
    apply(sql)
    seed(sql)
    for user, expected in [('00000000-0000-0000-0000-000000000001', '1'),
                           ('00000000-0000-0000-0000-000000000002', '0')]:
        result = sql(f"""set role authenticated;
          set request.jwt.claim.sub = '{user}'; select count(*) from trips_groups;""")
        assert result.returncode == 0 and result.stdout.strip().endswith(expected), result.stderr
    for query in ('select * from trips_groups;', 'delete from trips_groups;',
                  'update trips_groups set revision=100;', 'truncate trips_groups;'):
        role = 'anon' if query.startswith('select') else 'authenticated'
        result = sql(f'set role {role}; {query}')
        assert result.returncode != 0 and 'permission denied' in result.stderr


def test_agent_receipts_atomic_replay_mismatch_and_concurrent_requests(trips_database):
    import json
    from concurrent.futures import ThreadPoolExecutor

    sql = trips_database
    apply(sql)
    seed(sql)
    owner = '00000000-0000-0000-0000-000000000001'
    trip = '10000000-0000-0000-0000-000000000001'
    after = {'data': {'name': 'Agent committed', 'expenses': []}, 'member_user_ids': [owner],
             'revision': 2, 'updated_at': '2026-11-03T00:00:00Z'}

    def commit(payload='same', user=owner, revision=1, key='agent-key'):
        return sql("set role service_role; select trips_agent_commit(" + ','.join([
            migration_runner.sql_literal(user), migration_runner.sql_literal(key),
            migration_runner.sql_literal(json.dumps({'input': payload})), migration_runner.sql_literal(trip),
            str(revision), migration_runner.sql_literal(json.dumps(after)), "'{\"saved\":true}'"]) + ');')

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: commit(), range(8)))
    assert all(result.returncode == 0 and '"saved": true' in result.stdout for result in results), results
    assert sql('select revision from trips_groups;').stdout.strip() == '2'
    assert sql('select count(*) from trips_agent_receipts;').stdout.strip() == '1'
    assert 'idempotency' in commit(payload='different').stdout
    assert 'membership' in commit(user='00000000-0000-0000-0000-000000000002').stdout
    assert 'revision' in commit(key='other-key').stdout
    assert sql('select count(*) from trips_agent_receipts;').stdout.strip() == '1'
    assert sql('select revision from trips_groups;').stdout.strip() == '2'


@pytest.mark.parametrize('role', ['anon', 'authenticated'])
def test_agent_receipts_and_commit_are_service_only(trips_database, role):
    sql = trips_database
    apply(sql)
    for query in ('select * from trips_agent_receipts;',
                  "select trips_agent_commit(null,null,null,null,null,null,null);"):
        result = sql(f'set role {role}; {query}')
        assert result.returncode != 0 and 'permission denied' in result.stderr


@pytest.mark.parametrize('damage', ['alter table trips_agent_receipts disable row level security;',
    'grant select on trips_agent_receipts to authenticated;',
    'grant execute on function trips_agent_commit(uuid,text,jsonb,uuid,integer,jsonb,jsonb) to anon;'])
def test_agent_readiness_rejects_unsafe_grants(trips_database, damage):
    sql = trips_database
    apply(sql)
    assert sql(damage).returncode == 0
    result = sql('select trips_release_readiness();')
    assert result.returncode != 0 and 'receipt storage or grants changed' in result.stderr
