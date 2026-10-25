"""Admin-confirmed links from a trip member to an existing account, and their undo."""
from uuid import uuid4

import pytest

from tests.test_trips import local_api, trip  # noqa: F401 - shared fixture
from trips.ledger import LedgerError, apply_command, claim_invite, public_group


def link(row, user_id, member_index, account):
    return apply_command(row, user_id, 'link_member', {
        'revision': row['revision'], 'member_id': row['data']['members'][member_index]['id'], 'user_id': account})


def unlink(row, user_id, member_index, account=None):
    member = row['data']['members'][member_index]
    return apply_command(row, user_id, 'unlink_member', {
        'revision': row['revision'], 'member_id': member['id'], 'user_id': account or member['user_id']})


def test_link_replaces_invite_and_placeholder_venmo_and_keeps_a_private_audit():
    row, token = trip()
    row, _ = apply_command(row, 'matt', 'set_member_venmo', {
        'revision': row['revision'], 'member_id': row['data']['members'][2]['id'], 'venmo_username': 'jamie-v'})
    linked, invitation = link(row, 'matt', 2, 'jamie-account')
    jamie = linked['data']['members'][2]
    assert invitation is None and jamie['user_id'] == 'jamie-account'
    assert 'invite_hash' not in jamie and 'venmo_username' not in jamie
    assert linked['member_user_ids'] == ['matt', 'jamie-account']
    assert linked['data']['activity'][0]['summary'] == 'Linked Jamie to their account'
    assert linked['data']['account_links'] == [{'action': 'link', 'member_id': jamie['id'], 'user_id': 'jamie-account',
                                                'by': 'matt', 'at': linked['updated_at']}]
    assert 'account_links' not in public_group(linked)
    assert 'jamie-account' not in row['member_user_ids']  # Input is never mutated.
    with pytest.raises(LedgerError):
        claim_invite(linked, 'someone-else', token)


def test_unlink_revokes_access_keeps_history_and_issues_a_fresh_invite():
    row, _ = trip()
    row, _ = link(row, 'matt', 1, 'wrong-account')
    unlinked, token = unlink(row, 'matt', 1)
    alex = unlinked['data']['members'][1]
    assert alex['user_id'] is None and alex['name'] == 'Alex' and 'wrong-account' not in unlinked['member_user_ids']
    assert [entry['action'] for entry in unlinked['data']['account_links']] == ['link', 'unlink']
    assert unlinked['data']['account_links'][1]['user_id'] == 'wrong-account'
    joined = claim_invite(unlinked, 'right-account', token)
    assert joined['data']['members'][1]['user_id'] == 'right-account'
    with pytest.raises(LedgerError) as changed:  # A stale review must not revoke the corrected account.
        unlink(joined, 'matt', 1, 'wrong-account')
    assert changed.value.status == 409


@pytest.mark.parametrize('command, user_id, member_index, account, status', [
    ('link', 'jamie', 1, 'alex-account', 404),  # Not a member of the trip.
    ('link', 'matt', 0, 'other-account', 409),  # The creator's own place is already linked.
    ('link', 'matt', 1, 'matt', 409),  # The account already has a place.
    ('unlink', 'matt', 1, None, 409),  # Nothing to unlink.
    ('unlink', 'matt', 0, None, 422),  # The creator's own place.
])
def test_link_and_unlink_refuse_invalid_places(command, user_id, member_index, account, status):
    row, _ = trip()
    with pytest.raises(LedgerError) as error:
        link(row, user_id, member_index, account) if command == 'link' else unlink(row, user_id, member_index)
    assert error.value.status == status


def test_only_the_creator_links_and_stale_revisions_conflict():
    row, token = trip()
    row = claim_invite(row, 'jamie', token)
    with pytest.raises(LedgerError) as not_owner:
        link(row, 'jamie', 1, 'alex-account')
    assert not_owner.value.status == 403
    with pytest.raises(LedgerError) as not_owner:
        unlink(row, 'jamie', 2)
    assert not_owner.value.status == 403
    with pytest.raises(LedgerError) as stale:
        apply_command(row, 'matt', 'link_member', {
            'revision': 1, 'member_id': row['data']['members'][1]['id'], 'user_id': 'alex-account'})
    assert stale.value.status == 409


def test_real_admin_links_with_suggestions_and_unlinks(local_api, monkeypatch):  # noqa: F811
    api, admin, settings, tokens, ids = local_api
    alex_id = api.get('/trips/me', headers=tokens['Alex']).json()['user_id']
    group_id = str(uuid4())
    ids.append(group_id)
    base = f'/trips/groups/{group_id}'
    group = api.post('/trips/groups', headers=tokens['Matt'], json={'id': group_id, 'name': 'Link QA'}).json()
    group = api.post(f'{base}/members', headers=tokens['Matt'], json={'name': 'Alex', 'revision': group['revision']}).json()['group']
    place = group['members'][1]['id']
    attempt = {'revision': group['revision'], 'user_id': alex_id}
    suggestions = f'/trips/admin/groups/{group_id}/link-suggestions'

    # Without admin, even the creator can neither list accounts nor link them.
    assert api.get('/trips/me', headers=tokens['Matt']).json()['is_admin'] is False
    assert api.get(suggestions, headers=tokens['Matt']).status_code == 403
    assert api.post(f'{base}/members/{place}/link', headers=tokens['Matt'], json=attempt).status_code == 403

    monkeypatch.setattr('trips.routes.ADMIN_EMAILS', {'matt@trips.local', 'alex@trips.local'})
    assert api.get('/trips/me', headers=tokens['Matt']).json()['is_admin'] is True
    assert api.get(suggestions, headers=tokens['Alex']).status_code == 404  # An admin who isn't on the trip.
    # ...gets the same answer from the link endpoint whatever account they try, before any account is examined.
    outsider = {'revision': group['revision']}
    assert {api.post(f'{base}/members/{place}/link', headers=tokens['Alex'], json=outsider | {'user_id': uid}).status_code
            for uid in [alex_id, str(uuid4())]} == {404}
    listed = api.get(suggestions, headers=tokens['Matt'])
    assert listed.status_code == 200 and listed.headers['cache-control'] == 'no-store'
    assert listed.json()['revision'] == group['revision']
    assert [m['member_id'] for m in listed.json()['members']] == [place]  # Linked places, like the creator's, aren't offered.
    row = listed.json()['members'][0]
    assert (row['status'], row['user_id'], row['flags']) == ('suggested', alex_id, ['weak'])
    assert 'email' not in listed.text and '@trips.local' not in listed.text
    refused = api.post(f'{base}/members/{place}/link', headers=tokens['Matt'], json=attempt | {'user_id': str(uuid4())})
    assert refused.status_code == 404, refused.text
    assert api.get(base, headers=tokens['Alex']).status_code == 404

    # An identical twin, even one never shown, blocks linking at the API, not just on screen.
    import trips.routes
    real_accounts = trips.routes.read_accounts
    twin = {'names': ['Alex'], 'venmo_username': None, 'avatar_url': None}
    monkeypatch.setattr('trips.routes.read_accounts', lambda _client: [{'user_id': alex_id, **twin}, {'user_id': str(uuid4()), **twin}])
    blocked = api.post(f'{base}/members/{place}/link', headers=tokens['Matt'], json=attempt)
    assert blocked.status_code == 422 and 'told apart' in blocked.text
    # An account that isn't a likely match can't be linked by posting its ID directly.
    monkeypatch.setattr('trips.routes.read_accounts', lambda _client: [{'user_id': alex_id, 'names': ['Zed Unrelated'], 'venmo_username': None, 'avatar_url': None}])
    blind = api.post(f'{base}/members/{place}/link', headers=tokens['Matt'], json=attempt)
    assert blind.status_code == 422 and 'likely match' in blind.text
    monkeypatch.setattr('trips.routes.read_accounts', real_accounts)

    linked = api.post(f'{base}/members/{place}/link', headers=tokens['Matt'], json=attempt)
    assert linked.status_code == 200, linked.text
    assert linked.json()['members'][1]['user_id'] == alex_id and 'account_links' not in linked.text
    assert api.get(base, headers=tokens['Alex']).status_code == 200

    unlinked = api.post(f'{base}/members/{place}/unlink', headers=tokens['Matt'], json={'revision': linked.json()['revision'], 'user_id': alex_id})
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()['invite_token'] and unlinked.json()['group']['members'][1]['user_id'] is None
    assert api.get(base, headers=tokens['Alex']).status_code == 404
