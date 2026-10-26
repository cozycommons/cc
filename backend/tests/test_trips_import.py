from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from pydantic import ValidationError
import pytest

from trips.imports import prepare_import, require_same_import
from trips.ledger import LedgerError, balances
from tests.test_trips import local_api


@pytest.fixture
def snapshot():
    return {
        'format': 'cozy-trips-splitwise-v1', 'group_id': 'synthetic-trip',
        'name': 'Synthetic source trip', 'currency': 'USD', 'captured_at': '2026-10-23T06:00:00Z',
        'members': [{'id': 'a', 'name': 'Ari'}, {'id': 'b', 'name': 'Bo'}, {'id': 'c', 'name': 'Cam'}],
        'expenses': [
            {'id': 'expense-1', 'description': 'Shared ride', 'amount_minor': 1001, 'paid_by': 'a',
             'shares': {'a': 334, 'b': 334, 'c': 333}, 'date': '2026-10-20'},
            {'id': 'expense-2', 'description': 'Lunch', 'amount_minor': 900, 'paid_by': 'b',
             'shares': {'a': 300, 'b': 300, 'c': 300}, 'date': '2026-10-21'},
        ],
        'repayments': [{'id': 'payment-1', 'from_member': 'c', 'to_member': 'a',
                        'amount_minor': 100, 'date': '2026-10-22'}],
        'expected_balances': {'a': 267, 'b': 266, 'c': -533},
    }


def test_import_retains_exact_source_pennies_and_reconciles(snapshot):
    before = deepcopy(snapshot)
    row, report = prepare_import(snapshot, 'user-a', 'a')
    assert snapshot == before
    assert row['member_user_ids'] == ['user-a']
    assert [m['user_id'] for m in row['data']['members']] == ['user-a', None, None]
    people = {m['source_id']: m['id'] for m in row['data']['members']}
    assert row['data']['expenses'][0]['shares'] == {people['a']: 334, people['b']: 334, people['c']: 333}
    assert balances(row['data']) == {people['a']: 267, people['b']: 266, people['c']: -533}
    assert report['reconciled'] and report['expense_count'] == 2 and report['repayment_count'] == 1


def test_same_snapshot_and_new_capture_time_have_stable_identity(snapshot):
    first, _ = prepare_import(snapshot, 'user-a', 'a')
    snapshot['captured_at'] = '2026-10-24T06:00:00Z'
    second, _ = prepare_import(snapshot, 'user-a', 'a')
    assert first['id'] == second['id']
    assert first['data']['source']['snapshot_sha256'] == second['data']['source']['snapshot_sha256']
    assert [e['id'] for e in first['data']['expenses']] == [e['id'] for e in second['data']['expenses']]
    require_same_import(first, second)


def test_changed_contents_or_identity_mapping_require_review(snapshot):
    first, _ = prepare_import(snapshot, 'user-a', 'a')
    snapshot['expenses'][0]['notes'] = 'Changed upstream'
    changed, _ = prepare_import(snapshot, 'user-a', 'a')
    with pytest.raises(LedgerError, match='different contents'):
        require_same_import(first, changed)
    different_person, _ = prepare_import(snapshot, 'user-a', 'b')
    assert first['id'] == different_person['id']
    with pytest.raises(LedgerError):
        require_same_import(first, different_person)
    another_owner, _ = prepare_import(snapshot, 'user-b', 'b')
    assert first['id'] != another_owner['id']


@pytest.mark.parametrize('invalid', [0, -1, 1.1, True, '1001', 1_000_000_001])
def test_import_rejects_invalid_money(snapshot, invalid):
    snapshot['expenses'][0]['amount_minor'] = invalid
    with pytest.raises(ValidationError):
        prepare_import(snapshot, 'user-a', 'a')


@pytest.mark.parametrize('damage, message', [
    (lambda s: s['members'].append(s['members'][0]), 'distinct IDs'),
    (lambda s: s['expenses'].append(s['expenses'][0]), 'distinct IDs'),
    (lambda s: s['repayments'].append(s['repayments'][0]), 'distinct IDs'),
    (lambda s: s['expenses'][0].update(paid_by='outsider'), 'outside the trip'),
    (lambda s: s['expenses'][0]['shares'].update(outsider=0), 'outside the trip'),
    (lambda s: s['expenses'][0]['shares'].update(a=335), 'Shares do not equal'),
    (lambda s: s['expected_balances'].pop('b'), 'every person'),
    (lambda s: s['expected_balances'].update(a=268, b=265), 'does not reconcile'),
    (lambda s: s['repayments'][0].update(to_member='c'), 'two different'),
    (lambda s: s['repayments'][0].update(to_member='outsider'), 'two different'),
])
def test_invalid_source_is_rejected_before_saving(snapshot, damage, message):
    damage(snapshot)
    with pytest.raises(LedgerError, match=message):
        prepare_import(snapshot, 'user-a', 'a')


def test_distinct_identical_expenses_and_same_named_people_are_not_merged(snapshot):
    snapshot['members'][1]['name'] = snapshot['members'][0]['name']
    duplicate = deepcopy(snapshot['expenses'][0])
    duplicate['id'] = 'distinct-source-id'
    snapshot['expenses'].append(duplicate)
    snapshot['expected_balances'] = {'a': 934, 'b': -68, 'c': -866}
    row, report = prepare_import(snapshot, 'user-a', 'a')
    assert report['member_count'] == 3 and report['expense_count'] == 3
    assert len({e['id'] for e in row['data']['expenses']}) == 3


def test_owner_mapping_and_source_limits(snapshot):
    with pytest.raises(LedgerError, match='Choose your person'):
        prepare_import(snapshot, 'user-a', 'outsider')
    snapshot['currency'] = 'JPY'
    with pytest.raises(ValidationError):
        prepare_import(snapshot, 'user-a', 'a')


def test_real_supabase_import_preview_atomicity_retry_and_edit_preservation(local_api, snapshot):
    api, admin, settings, tokens, cleanup_ids = local_api
    snapshot['group_id'] = str(uuid4())
    payload = {'snapshot': snapshot, 'own_member_id': 'a'}
    assert api.post('/trips/imports/preview', json=payload).status_code == 401
    result = api.post('/trips/imports/preview', json=payload, headers=tokens['Matt'])
    assert result.status_code == 200, result.text
    preview = result.json()
    assert preview['status'] == 'preview' and preview['report']['reconciled']
    group_id = preview['group']['id']
    cleanup_ids.append(group_id)
    base = f'/trips/groups/{group_id}'
    assert api.get(base, headers=tokens['Matt']).status_code == 404
    invalid = deepcopy(payload)
    invalid['snapshot']['expected_balances']['a'] += 1
    assert api.post('/trips/imports', json=invalid, headers=tokens['Matt']).status_code == 400
    assert admin.table('trips_groups').select('id').eq('id', group_id).execute().data == []
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: api.post('/trips/imports', json=payload, headers=tokens['Matt']), range(2)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert {r.json()['status'] for r in responses} <= {'created', 'existing'}
    group = api.get(base, headers=tokens['Matt']).json()
    assert group['revision'] == 1 and len(group['expenses']) == 2
    assert api.get(base, headers=tokens['Alex']).status_code == 404
    item = group['expenses'][0]
    edit = {key: item[key] for key in ['id', 'description', 'amount_minor', 'paid_by', 'date', 'category', 'split_mode', 'shares']}
    edit.update(participants=list(item['shares']), revision=group['revision'], notes='Edited in Trips')
    result = api.put(f"{base}/expenses/{item['id']}", headers=tokens['Matt'], json=edit)
    assert result.status_code == 200, result.text
    assert result.json()['expenses'][0]['source_id'] == 'expense-1'
    repeated = api.post('/trips/imports', json=payload, headers=tokens['Matt']).json()
    assert repeated['status'] == 'existing'
    assert repeated['group']['revision'] == 2
    assert repeated['group']['expenses'][0]['notes'] == 'Edited in Trips'
    changed = deepcopy(payload)
    changed['snapshot']['expenses'][0]['notes'] = 'Changed upstream'
    assert api.post('/trips/imports', json=changed, headers=tokens['Matt']).status_code == 409
    assert len(admin.table('trips_groups').select('id').eq('id', group_id).execute().data) == 1


def test_import_starts_gated(snapshot):
    from trips.ledger import public_group
    row, _ = prepare_import(snapshot, 'user-a', 'a')
    assert row['data']['settle'] == {'started_at': None, 'started_by': None, 'ready': {}}
    assert not public_group(row)['obligations']
    assert public_group(row)['transfers']
