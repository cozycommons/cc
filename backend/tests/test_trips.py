"""Trip money rules and real local Supabase authorization/atomicity checks."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from supabase import create_client

from trips.ledger import LedgerError, apply_command, balances, claim_invite, new_group, public_group, transfers


def trip():
    row = new_group(str(uuid4()), 'matt', 'Cabin weekend', 'USD', 'Matt')
    row, _ = apply_command(row, 'matt', 'add_member', {'revision': row['revision'], 'name': 'Alex'})
    row, token = apply_command(row, 'matt', 'add_member', {'revision': row['revision'], 'name': 'Jamie'})
    return row, token


def expense(row, amount=12001, **overrides):
    return dict(id=str(uuid4()), revision=row['revision'], description='Dinner', amount_minor=amount,
                paid_by=row['data']['members'][0]['id'], split_mode='equal',
                participants=[m['id'] for m in row['data']['members']], shares={},
                date='2026-10-22', category='food', notes='') | overrides


def test_pennies_are_deterministic_and_balance_is_zero_sum():
    row, _ = trip()
    before = deepcopy(row)
    payload = expense(row)
    payload['participants'].reverse()
    after, _ = apply_command(row, 'matt', 'add_expense', payload)
    ids = [m['id'] for m in row['data']['members']]
    assert row == before
    assert after['data']['expenses'][0]['shares'] == dict(zip(ids, [4001, 4000, 4000]))
    assert balances(after['data']) == dict(zip(ids, [8000, -4000, -4000]))
    assert sum(balances(after['data']).values()) == 0
    assert 'invite_hash' not in json.dumps(public_group(after))


def test_exact_split_exclusion_edit_and_delete_recalculate():
    row, _ = trip()
    ids = [m['id'] for m in row['data']['members']]
    item = expense(row, 10000, split_mode='exact', participants=ids[1:], shares={ids[1]: 2500, ids[2]: 7500})
    row, _ = apply_command(row, 'matt', 'add_expense', item)
    assert list(balances(row['data']).values()) == [10000, -2500, -7500]
    item.update(revision=row['revision'], amount_minor=9000, shares={ids[1]: 2000, ids[2]: 7000})
    row, _ = apply_command(row, 'matt', 'edit_expense', item)
    assert list(balances(row['data']).values()) == [9000, -2000, -7000]
    row, _ = apply_command(row, 'matt', 'delete_expense', {'revision': row['revision'], 'id': item['id']})
    assert list(balances(row['data']).values()) == [0, 0, 0]


@pytest.mark.parametrize('overrides', [
    {'participants': []}, {'participants': ['someone-else']},
    {'paid_by': 'someone-else'}, {'split_mode': 'exact', 'shares': {}},
])
def test_invalid_splits_are_rejected(overrides):
    row, _ = trip()
    with pytest.raises(LedgerError):
        apply_command(row, 'matt', 'add_expense', expense(row, **overrides))


def test_stale_edits_and_nonmembers_are_rejected():
    row, _ = trip()
    with pytest.raises(LedgerError) as stale:
        apply_command(row, 'matt', 'add_expense', expense(row, revision=1))
    assert stale.value.status == 409
    with pytest.raises(LedgerError) as outsider:
        apply_command(row, 'outsider', 'add_expense', expense(row))
    assert outsider.value.status == 404


def test_repayments_settle_and_undo_without_creating_money():
    row, _ = trip()
    row, _ = apply_command(row, 'matt', 'add_expense', expense(row))
    for transfer in transfers(balances(row['data'])):
        row, _ = apply_command(row, 'matt', 'add_repayment',
                               transfer | {'id': str(uuid4()), 'revision': row['revision'], 'date': '2026-10-22', 'notes': ''})
    assert set(balances(row['data']).values()) == {0}
    assert transfers(balances(row['data'])) == []
    item = row['data']['repayments'][0]
    row, _ = apply_command(row, 'matt', 'delete_repayment', {'id': item['id'], 'revision': row['revision']})
    assert sum(balances(row['data']).values()) == 0
    assert transfers(balances(row['data']))


def test_invites_are_single_use_and_cannot_claim_another_place():
    row, token = trip()
    with pytest.raises(LedgerError):
        claim_invite(row, 'matt', token)
    joined = claim_invite(row, 'jamie', token)
    assert 'jamie' in joined['member_user_ids']
    assert joined['data']['members'][2]['user_id'] == 'jamie'
    with pytest.raises(LedgerError):
        claim_invite(joined, 'attacker', token)
    with pytest.raises(LedgerError):
        apply_command(joined, 'jamie', 'add_member', {'revision': joined['revision'], 'name': 'Other'})


@pytest.fixture
def local_api(monkeypatch):
    if os.environ.get('TRIPS_INTEGRATION') != '1':
        pytest.skip('Enable TRIPS_INTEGRATION=1 for the dedicated local Trips Supabase project.')
    root = Path(__file__).resolve().parents[2]
    settings = json.loads(subprocess.check_output([str(root / 'node_modules/.bin/supabase'),
                                                  '--workdir', str(root / '.trips-dev'), 'status', '-o', 'json'],
                                                 text=True, stderr=subprocess.DEVNULL))
    assert settings['API_URL'] == 'http://127.0.0.1:55321'
    admin = create_client(settings['API_URL'], settings['SERVICE_ROLE_KEY'])
    monkeypatch.setenv('COZY_TRIPS_LOCAL', '1')
    monkeypatch.setenv('SUPABASE_URL', settings['API_URL'])
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', settings['SERVICE_ROLE_KEY'])
    from trips.local import app
    assert app.state.runtime_policy.is_trips_sandbox
    assert not app.state.runtime_policy.allow_external_side_effects
    tokens = {}
    for name in ['Matt', 'Alex', 'Jamie']:
        sb = create_client(settings['API_URL'], settings['ANON_KEY'])
        session = sb.auth.sign_in_with_password({'email': f'{name.lower()}@trips.local', 'password': 'local-trips-password'}).session
        tokens[name] = {'Authorization': f'Bearer {session.access_token}'}
    ids = []
    with TestClient(app) as api:
        yield api, admin, settings, tokens, ids
    for group_id in ids:
        admin.table('trips_groups').delete().eq('id', group_id).execute()


def test_real_api_persistence_invites_rls_validation_and_concurrency(local_api):
    api, admin, settings, tokens, cleanup_ids = local_api
    group_id = str(uuid4())
    cleanup_ids.append(group_id)
    matt, alex, jamie = tokens['Matt'], tokens['Alex'], tokens['Jamie']
    base = f'/trips/groups/{group_id}'
    assert api.get('/trips/groups').status_code == 401
    assert api.get('/trips/groups', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    result = api.post('/trips/groups', headers=matt, json={'id': group_id, 'name': 'Disposable API QA trip', 'display_name': 'Matt', 'currency': 'USD'})
    assert result.status_code == 201, result.text
    group = result.json()
    assert api.get(base, headers=alex).status_code == 404
    assert group_id not in [g['id'] for g in api.get('/trips/groups', headers=alex).json()]
    result = api.post(f'{base}/members', headers=matt, json={'revision': group['revision'], 'name': 'Alex'})
    assert result.status_code == 201, result.text
    group, invite = result.json()['group'], result.json()['invite_token']
    assert 'invite_hash' not in result.text
    wrong = api.post(f'{base}/join', headers=alex, json={'invite_token': 'x' * 43})
    assert wrong.status_code == 404
    result = api.post(f'{base}/join', headers=alex, json={'invite_token': invite})
    assert result.status_code == 200, result.text
    group = result.json()
    assert api.post(f'{base}/join', headers=jamie, json={'invite_token': invite}).status_code == 404
    assert api.post(f'{base}/members', headers=alex, json={'revision': group['revision'], 'name': 'Other'}).status_code == 403
    # Direct Data API reads are scoped by RLS; client writes are denied.
    headers = {'apikey': settings['ANON_KEY'], **jamie}
    import httpx
    url = f"{settings['API_URL']}/rest/v1/trips_groups?id=eq.{group_id}"
    assert httpx.get(url, headers=headers).json() == []
    assert httpx.get(url, headers={'apikey': settings['ANON_KEY'], **alex}).json()[0]['id'] == group_id
    assert httpx.patch(url, headers={'apikey': settings['ANON_KEY'], **matt}, json={'revision': 100}).status_code == 403
    assert httpx.get(url, headers={'apikey': settings['ANON_KEY']}).status_code in [401, 403]
    people = [m['id'] for m in group['members']]
    payload = dict(id=str(uuid4()), revision=group['revision'], description='Lunch', amount_minor=10001,
                   paid_by=people[0], split_mode='equal', participants=people, date='2026-10-22', category='food')
    for invalid in [0, -1, 100.01, True]:
        assert api.post(f'{base}/expenses', headers=matt, json=payload | {'amount_minor': invalid}).status_code == 422
    assert api.post(f'{base}/expenses', headers=matt, json=payload | {'split_mode': 'exact', 'shares': {people[0]: 10001}}).status_code == 400
    assert api.post(f'{base}/expenses', headers=jamie, json=payload).status_code == 404
    assert api.post(f'{base}/expenses', headers=matt, json=payload | {'paid_by': str(uuid4())}).status_code == 400
    # Two valid writes from the same revision: exactly one may commit.
    def write(index):
        return api.post(f'{base}/expenses', headers=alex, json=payload | {'id': str(uuid4()), 'description': f'Race {index}'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(write, [1, 2]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    group = api.get(base, headers=matt).json()
    assert len(group['expenses']) == 1 and group['total_minor'] == 10001
    assert sum(group['balances'].values()) == 0
    item = group['expenses'][0]
    edit = payload | {'id': item['id'], 'revision': group['revision'], 'amount_minor': 12000, 'description': 'Dinner'}
    group = api.put(f"{base}/expenses/{item['id']}", headers=alex, json=edit).json()
    assert group['total_minor'] == 12000
    payment = group['transfers'][0] | {'id': str(uuid4()), 'revision': group['revision'], 'date': '2026-10-22', 'notes': 'Test payment'}
    result = api.post(f'{base}/repayments', headers=alex, json=payment)
    assert result.status_code == 201, result.text
    group = result.json()
    assert set(group['balances'].values()) == {0}
    group = api.request('DELETE', f"{base}/repayments/{payment['id']}", headers=matt, json={'revision': group['revision']}).json()
    assert group['transfers']
    group = api.request('DELETE', f"{base}/expenses/{item['id']}", headers=alex, json={'revision': group['revision']}).json()
    assert group['total_minor'] == 0 and set(group['balances'].values()) == {0}
    assert admin.table('trips_groups').select('revision').eq('id', group_id).execute().data[0]['revision'] == group['revision']


def test_trips_migrations_are_included_in_shared_release(monkeypatch):
    import migration_runner
    script = migration_runner.render(['trips'])
    assert 'Applying 0001_trips_ledger.sql' in script
    assert 'trips_schema_migrations' in script
    assert 'ENABLE ROW LEVEL SECURITY' in script
    assert 'Existing trips schema has no migration history' in script
    captured = []
    from types import SimpleNamespace
    monkeypatch.setenv('SUPABASE_DB_URL', 'postgresql://postgres:postgres@127.0.0.1:55322/postgres')
    monkeypatch.setattr('sys.argv', ['migration_runner.py', '--family', 'all'])
    monkeypatch.setattr(migration_runner.subprocess, 'run', lambda *args, **kwargs: captured.append(kwargs['input']) or SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit) as result:
        migration_runner.main()
    assert result.value.code == 0
    assert 'Applying 0001_trips_ledger.sql' in captured[0]
    assert 'Applying 0080_dice_release_readiness_commons_0012.sql' in captured[0]
