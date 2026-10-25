"""Venmo usernames, owner-set placeholders, weighted splits and retried creates."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.test_trips import expense, local_api, trip  # noqa: F401 - shared fixture
from tests.test_trips_profiles import ProfileClient
from trips.ledger import LedgerError, apply_command, balances, claim_invite, new_group, weighted_shares
from trips.profiles import render_groups
from trips.routes import already_saved
from trips.venmo import account_venmo, normalize_username


@pytest.mark.parametrize('raw, expected', [
    ('@Jayce-e', 'Jayce-e'), ('  keungjason ', 'keungjason'), ('https://venmo.com/u/bchen0702', 'bchen0702'),
    ('venmo.com/andsohn?txn=pay', 'andsohn'), ('account.venmo.com/u/azizrahman111', 'azizrahman111'),
    ('', None), ('@', None), (None, None)])
def test_usernames_normalize_without_changing_case(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize('raw', ['abc', 'a' * 31, 'has space', 'semi;colon', 'émile-x', 'x/../y', '@@double'])
def test_invalid_usernames_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_username(raw)


def test_seeded_usernames_stay_unconfirmed_and_bad_metadata_is_ignored():
    seeded = {'venmo_username': 'mattsho', 'venmo_username_provenance': {'source': 'matt_provided', 'owner_confirmed': False}}
    assert account_venmo(seeded) == {'venmo_username': 'mattsho', 'venmo_confirmed': False}
    assert account_venmo({'venmo_username': 'mattsho'}) == {'venmo_username': 'mattsho', 'venmo_confirmed': False}
    self_saved = {'venmo_username': 'mattsho', 'venmo_username_provenance': {'source': 'self', 'owner_confirmed': True}}
    assert account_venmo(self_saved) == {'venmo_username': 'mattsho', 'venmo_confirmed': True}
    assert account_venmo({'venmo_username': 'mattsho', 'venmo_username_provenance': 'yes'})['venmo_confirmed'] is False
    assert account_venmo({'venmo_username': 'javascript:alert(1)'}) == {'venmo_username': None, 'venmo_confirmed': False}
    assert account_venmo({'venmo_username': ['list']}) == {'venmo_username': None, 'venmo_confirmed': False}


def test_render_reads_handles_only_from_linked_accounts_and_owner_placeholders():
    row = new_group(str(uuid4()), 'owner-1', 'Trip', 'USD', 'Owner')
    row['data']['members'] += [{'id': 'linked', 'name': 'Guest', 'user_id': 'linked-2'},
                               {'id': 'placeholder', 'name': 'Not joined', 'user_id': None, 'venmo_username': 'trip-handle'}]
    mine = {'source': 'self', 'owner_confirmed': True}
    accounts = {'owner-1': SimpleNamespace(id='owner-1', user_metadata={'venmo_username': 'owner-handle', 'venmo_username_provenance': mine}),
                'linked-2': SimpleNamespace(id='linked-2', user_metadata={})}
    client = ProfileClient([], accounts)
    members = render_groups(client, [row])[0]['members']
    assert [(m['venmo_username'], m['venmo_source'], m['venmo_confirmed']) for m in members] == [
        ('owner-handle', 'account', True), (None, None, False), ('trip-handle', 'trip', False)]
    assert sorted(client.account_queries) == ['linked-2', 'owner-1']


def test_only_the_owner_sets_placeholder_handles_and_joining_hands_it_to_the_account():
    row, token = trip()
    jamie = row['data']['members'][2]['id']
    payload = {'revision': row['revision'], 'member_id': jamie, 'venmo_username': 'jamie-v'}
    with pytest.raises(LedgerError) as outsider:
        apply_command(row, 'someone', 'set_member_venmo', payload)
    assert outsider.value.status == 404
    row, _ = apply_command(row, 'matt', 'set_member_venmo', payload)
    assert row['data']['members'][2]['venmo_username'] == 'jamie-v'
    owner = row['data']['members'][0]['id']
    with pytest.raises(LedgerError) as linked:
        apply_command(row, 'matt', 'set_member_venmo', payload | {'revision': row['revision'], 'member_id': owner})
    assert linked.value.status == 409
    joined = claim_invite(row, 'jamie', token)
    assert 'venmo_username' not in joined['data']['members'][2]
    alex = joined['data']['members'][1]['id']
    with pytest.raises(LedgerError) as not_owner:
        apply_command(joined, 'jamie', 'set_member_venmo', payload | {'revision': joined['revision'], 'member_id': alex})
    assert not_owner.value.status == 403
    row, _ = apply_command(row, 'matt', 'set_member_venmo', payload | {'revision': row['revision'], 'venmo_username': None})
    assert 'venmo_username' not in row['data']['members'][2]
    assert sum(balances(row['data']).values()) == 0


@pytest.mark.parametrize('amount, weights, expected', [
    (1000, {'a': 2, 'b': 1}, {'a': 667, 'b': 333}),
    (100, {'a': 1, 'b': 1, 'c': 1}, {'a': 34, 'b': 33, 'c': 33}),
    (1, {'a': 1, 'b': 3}, {'a': 0, 'b': 1}),
    (999_999_999, {'a': 7, 'b': 13, 'c': 1000}, None),
])
def test_weighted_shares_sum_exactly(amount, weights, expected):
    shares = weighted_shares(amount, weights)
    assert sum(shares.values()) == amount
    if expected:
        assert shares == expected


def test_shares_mode_stores_weights_and_switching_mode_drops_them():
    row, _ = trip()
    ids = [m['id'] for m in row['data']['members']]
    item = expense(row, 10000, split_mode='shares', participants=ids, shares={ids[0]: 2, ids[1]: 1, ids[2]: 1})
    row, _ = apply_command(row, 'matt', 'add_expense', item)
    saved = row['data']['expenses'][0]
    assert saved['shares'] == {ids[0]: 5000, ids[1]: 2500, ids[2]: 2500}
    assert saved['weights'] == {ids[0]: 2, ids[1]: 1, ids[2]: 1}
    row, _ = apply_command(row, 'matt', 'edit_expense', item | {'revision': row['revision'], 'split_mode': 'equal', 'shares': {}})
    assert 'weights' not in row['data']['expenses'][0]
    for bad in [{ids[0]: 0, ids[1]: 1, ids[2]: 1}, {ids[0]: 1}, {ids[0]: 1001, ids[1]: 1, ids[2]: 1}]:
        with pytest.raises(LedgerError):
            apply_command(row, 'matt', 'edit_expense', item | {'revision': row['revision'], 'shares': bad})


def test_retried_creates_are_idempotent_but_changed_retries_conflict():
    row, _ = trip()
    ids = [m['id'] for m in row['data']['members']]
    item = expense(row)
    row, _ = apply_command(row, 'matt', 'add_expense', item)
    assert already_saved(row, 'matt', 'add_expense', item)
    assert already_saved(row, 'matt', 'add_expense', item | {'participants': ids[::-1]})  # Same people, same record.
    for changed in [{'amount_minor': 1}, {'participants': ids[:2]}, {'notes': 'different'}, {'category': 'stay'},
                    {'split_mode': 'exact', 'shares': {ids[0]: 12001, ids[1]: 0, ids[2]: 0}}]:
        with pytest.raises(LedgerError) as conflict:
            already_saved(row, 'matt', 'add_expense', item | changed)
        assert conflict.value.status == 409, changed
    assert not already_saved(row, 'matt', 'add_expense', item | {'id': str(uuid4())})
    assert not already_saved(row, 'matt', 'edit_expense', item)
    payment = {'id': str(uuid4()), 'revision': row['revision'], 'from_member': ids[1], 'to_member': ids[0],
               'amount_minor': 4000, 'date': '2026-10-23', 'notes': 'Venmo'}
    row, _ = apply_command(row, 'matt', 'add_repayment', payment)
    assert already_saved(row, 'matt', 'add_repayment', payment)
    with pytest.raises(LedgerError):
        already_saved(row, 'matt', 'add_repayment', payment | {'notes': 'cash'})


def test_committed_writes_survive_profile_lookup_failures():
    row = new_group(str(uuid4()), 'owner-1', 'Trip', 'USD', 'Owner')

    class Unavailable(ProfileClient):
        def account(self, user_id):
            raise RuntimeError('auth unavailable')

    member = render_groups(Unavailable([]), [row])[0]['members'][0]
    assert member['display_name'] == 'Owner' and member['venmo_username'] is None

    class NoDice(ProfileClient):
        def execute(self):
            raise RuntimeError('dice_profiles unavailable')

    accounts = {'owner-1': SimpleNamespace(id='owner-1', user_metadata={'full_name': 'Account name'})}
    member = render_groups(NoDice([], accounts), [row])[0]['members'][0]
    assert member['display_name'] == 'Account name'


def test_real_own_username_persistence_and_isolation(local_api):  # noqa: F811
    api, admin, settings, tokens, ids = local_api
    me = api.get('/trips/me', headers=tokens['Alex']).json()
    original = admin.auth.admin.get_user_by_id(me['user_id']).user.user_metadata
    try:
        saved = api.put('/trips/me', headers=tokens['Alex'], json={'venmo_username': '@Alex-Local_1', 'owner_confirmed': True})
        assert saved.status_code == 200, saved.text
        assert saved.json()['venmo_username'] == 'Alex-Local_1' and saved.json()['venmo_confirmed']
        metadata = admin.auth.admin.get_user_by_id(me['user_id']).user.user_metadata
        assert metadata['full_name'] == original['full_name']  # Other metadata is preserved.
        assert metadata['venmo_username_provenance']['provided_by_user_id'] == me['user_id']
        assert api.get('/trips/me', headers=tokens['Alex']).json()['venmo_username'] == 'Alex-Local_1'
        assert api.put('/trips/me', headers=tokens['Alex'], json={'venmo_username': 'no'}).status_code == 422
        assert api.put('/trips/me', headers=tokens['Alex'], json={'venmo_username': 'alex-x', 'user_id': 'other'}).status_code == 422
        assert api.put('/trips/me', json={'venmo_username': 'alex-local'}).status_code == 401
        assert api.get('/trips/me', headers=tokens['Alex']).json()['venmo_username'] == 'Alex-Local_1'
        changed = api.put('/trips/me', headers=tokens['Alex'], json={'venmo_username': 'new-local-handle'}).json()
        assert not changed['venmo_confirmed']
        cleared = api.put('/trips/me', headers=tokens['Alex'], json={'venmo_username': ''}).json()
        assert cleared['venmo_username'] is None
        assert not admin.auth.admin.get_user_by_id(me['user_id']).user.user_metadata.get('venmo_username')
    finally:
        admin.auth.admin.update_user_by_id(me['user_id'], {'user_metadata': {
            'venmo_username': original.get('venmo_username'),
            'venmo_username_provenance': original.get('venmo_username_provenance')}})


def test_real_trip_exposes_handles_only_to_members(local_api):  # noqa: F811
    api, admin, settings, tokens, ids = local_api
    group_id = str(uuid4())
    ids.append(group_id)
    group = api.post('/trips/groups', headers=tokens['Matt'], json={'id': group_id, 'name': 'Venmo QA'}).json()
    base = f'/trips/groups/{group_id}'
    added = api.post(f'{base}/members', headers=tokens['Matt'], json={'name': 'Placeholder', 'revision': group['revision']}).json()['group']
    placeholder = added['members'][1]['id']
    result = api.put(f'{base}/members/{placeholder}/venmo', headers=tokens['Matt'],
                     json={'venmo_username': 'placeholder-v', 'revision': added['revision']})
    assert result.status_code == 200, result.text
    assert result.json()['members'][1]['venmo_username'] == 'placeholder-v'
    assert result.json()['members'][1]['venmo_source'] == 'trip'
    assert api.put(f'{base}/members/{placeholder}/venmo', headers=tokens['Jamie'],
                   json={'venmo_username': 'stolen-v', 'revision': result.json()['revision']}).status_code == 404
    assert api.get(base, headers=tokens['Jamie']).status_code == 404
    item = {'id': str(uuid4()), 'description': 'Retry', 'amount_minor': 500, 'paid_by': added['members'][0]['id'],
            'split_mode': 'equal', 'participants': [m['id'] for m in added['members']], 'shares': {},
            'date': '2026-10-23', 'category': 'food', 'notes': '', 'revision': result.json()['revision']}
    first = api.post(f'{base}/expenses', headers=tokens['Matt'], json=item)
    retry = api.post(f'{base}/expenses', headers=tokens['Matt'], json=item)
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json()['revision'] == first.json()['revision'] and len(retry.json()['expenses']) == 1


def test_confirmation_is_bound_to_the_handle_that_was_confirmed():
    assert account_venmo({'venmo_username': 'alex-new', 'venmo_username_provenance': {'owner_confirmed': True, 'handle': 'alex-old'}})['venmo_confirmed'] is False
    assert account_venmo({'venmo_username': 'Alex-New', 'venmo_username_provenance': {'owner_confirmed': True, 'handle': 'alex-new'}})['venmo_confirmed'] is True
