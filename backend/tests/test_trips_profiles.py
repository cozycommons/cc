"""Canonical profile reuse and the shared Commons application composition."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from gotrue.errors import AuthApiError

from trips.profiles import avatar_url, current_profile, render_groups, stored_profile
from tests.test_trips import local_api
from trips.ledger import new_group


def commons(user_id, name, avatar=None, venmo=None, confirmed=False, confirmed_name=None):
    return {'user_id': user_id, 'display_name': name, 'avatar_url': avatar, 'venmo_username': venmo,
            'venmo_owner_confirmed': confirmed, 'venmo_confirmed_name': confirmed_name}


class ProfileClient:
    def __init__(self, rows, accounts=None):
        self.rows, self.queries, self.inserted = rows, [], []
        self.accounts, self.account_queries = accounts or {}, []
        self.auth = SimpleNamespace(admin=SimpleNamespace(get_user_by_id=self.account))

    def account(self, user_id):
        self.account_queries.append(user_id)
        if user_id not in self.accounts:
            raise AuthApiError('User not found', 404, 'user_not_found')
        return SimpleNamespace(user=self.accounts[user_id])

    def table(self, name):
        self.name, self.row = name, None
        assert name in {'commons_profiles', 'dice_profiles'}
        return self

    def select(self, columns):
        self.columns = columns.split(',')
        return self

    def in_(self, column, ids):
        assert column == 'user_id'
        self.ids = ids
        self.queries.append(list(ids))
        return self

    def eq(self, column, value):
        self.ids = [value]
        return self

    def limit(self, _):
        return self

    def insert(self, row):
        assert self.name == 'commons_profiles'
        self.row = row
        return self

    def execute(self):
        if self.row is not None:
            self.rows.append(self.row)
            self.inserted.append(self.row)
            return SimpleNamespace(data=[self.row])
        if self.name == 'dice_profiles':
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[{c: row.get(c) for c in self.columns} for row in self.rows if row['user_id'] in self.ids])


def test_only_linked_member_ids_are_resolved_and_source_names_are_preserved():
    row = new_group(str(uuid4()), 'owner-1', 'Trip', 'USD', 'Source name')
    row['data']['members'].append({'id': 'unclaimed', 'name': 'Another profile name', 'user_id': None})
    before = deepcopy(row)
    client = ProfileClient([
        commons('owner-1', 'Existing Commons name', '/avatar.png', 'owner-pays', True, 'Owner Pays'),
        commons('outsider', 'Another profile name', '/private.png'),
    ])
    group = render_groups(client, [row])[0]
    assert client.queries == [['owner-1']]
    assert client.account_queries == []  # Every linked member has a Commons row.
    owner = group['members'][0]
    assert owner['name'] == 'Source name'
    assert owner['display_name'] == 'Existing Commons name'
    assert owner['avatar_url'] == '/avatar.png'
    assert (owner['venmo_username'], owner['venmo_confirmed'], owner['venmo_confirmed_name']) == ('owner-pays', True, 'Owner Pays')
    assert group['members'][1]['avatar_url'] is None
    assert group['members'][1]['user_id'] is None
    assert row == before


def test_current_account_creates_its_commons_profile_without_a_dice_profile():
    client = ProfileClient([])
    user = SimpleNamespace(id='new-user', email='new@example.test', is_anonymous=False,
                           user_metadata={'full_name': 'New friend', 'avatar_url': 'https://example.com/avatar.png'})
    profile = current_profile(client, user)
    assert profile == {'user_id': 'new-user', 'display_name': 'New friend',
                       'avatar_url': 'https://example.com/avatar.png', 'profile_source': 'commons',
                       'venmo_username': None, 'venmo_confirmed': False}
    assert [row['user_id'] for row in client.inserted] == ['new-user']
    assert current_profile(client, user) == profile and len(client.inserted) == 1


def test_anonymous_session_reads_account_metadata_and_creates_nothing():
    client = ProfileClient([])
    user = SimpleNamespace(id='guest', is_anonymous=True, user_metadata={'full_name': 'Guest'})
    assert current_profile(client, user)['profile_source'] == 'account'
    assert stored_profile(client, user)['display_name'] == 'Guest' and client.inserted == []


def test_linked_account_metadata_fills_missing_commons_profile_without_name_matching():
    row = new_group(str(uuid4()), 'owner-1', 'Trip', 'USD', 'Imported owner')
    row['data']['members'] += [{'id': 'guest', 'name': 'Imported guest', 'user_id': 'linked-2'},
                               {'id': 'unclaimed', 'name': 'Canonical guest', 'user_id': None}]
    before = deepcopy(row)
    account = SimpleNamespace(id='linked-2', user_metadata={'full_name': 'Canonical guest', 'avatar_url': 'https://example.com/guest.png',
                                                           'venmo_username': 'guest-pays'})
    client = ProfileClient([commons('owner-1', 'Commons owner', '/owner.png')], {'linked-2': account})
    groups = render_groups(client, [row, row])
    assert client.account_queries == ['linked-2']  # Only linked IDs without a Commons row, deduplicated.
    assert groups[0]['members'][0]['display_name'] == 'Commons owner'
    assert groups[0]['members'][1]['display_name'] == 'Canonical guest'
    assert groups[0]['members'][1]['avatar_url'] == 'https://example.com/guest.png'
    assert groups[0]['members'][1]['venmo_username'] == 'guest-pays'
    assert groups[0]['members'][1]['name'] == 'Imported guest'
    assert groups[0]['members'][2]['user_id'] is None
    assert groups[0]['members'][2]['avatar_url'] is None
    assert row == before


def test_deleted_linked_account_retains_source_identity():
    row = new_group(str(uuid4()), 'deleted-user', 'Trip', 'USD', 'Historical owner')
    group = render_groups(ProfileClient([]), [row])[0]
    assert group['members'][0]['display_name'] == 'Historical owner'
    assert group['members'][0]['avatar_url'] is None


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:image/svg+xml,bad', '//example.com/a.png',
                               'https://user:password@example.com/a.png', 'https://[bad', None])
def test_unusable_avatar_metadata_does_not_break_the_trip(url):
    assert avatar_url(url) is None


def test_real_shared_identity_profile_reuse_and_no_dice_creation(local_api):
    api, admin, settings, tokens, ids = local_api
    assert api.get('/ready').status_code == 200
    assert api.get('/health').status_code == 200
    assert api.get('/trips/me').status_code == 401
    matt = api.get('/trips/me', headers=tokens['Matt']).json()
    assert matt['profile_source'] == 'commons'
    assert api.get('/dice/me', headers=tokens['Matt']).json()['user_id'] == matt['user_id']
    jamie = api.get('/trips/me', headers=tokens['Jamie']).json()
    jamie_id = jamie['user_id']
    assert jamie['profile_source'] == 'commons'
    assert admin.table('commons_profiles').select('display_name').eq('user_id', jamie_id).execute().data != []
    assert admin.table('dice_profiles').select('user_id').eq('user_id', jamie_id).execute().data == []
    group_id = str(uuid4())
    ids.append(group_id)
    result = api.post('/trips/groups', headers=tokens['Matt'], json={'id': group_id, 'name': 'Shared identity QA'})
    assert result.status_code == 201, result.text
    group = result.json()
    assert group['members'][0]['display_name'] == matt['display_name']
    assert group['members'][0]['user_id'] == matt['user_id']
    base = f'/trips/groups/{group_id}'
    result = api.post(f'{base}/members', headers=tokens['Matt'], json={'name': 'Source guest name', 'revision': group['revision']})
    group, invite = result.json()['group'], result.json()['invite_token']
    guest = group['members'][1]
    assert guest['user_id'] is None and guest['avatar_url'] is None
    joined = api.post(f'{base}/join', headers=tokens['Jamie'], json={'invite_token': invite}).json()
    assert joined['members'][1]['display_name'] == jamie['display_name']
    assert joined['members'][1]['avatar_url'] == jamie['avatar_url']
    assert admin.table('dice_profiles').select('user_id').eq('user_id', jamie_id).execute().data == []
    original = admin.table('commons_profiles').select('display_name,avatar_url').eq('user_id', jamie_id).execute().data[0]
    try:
        # Opening Dice creates its row from the Commons profile; a Dice edit then reaches Trips.
        assert api.get('/dice/me', headers=tokens['Jamie']).json()['display_name'] == jamie['display_name']
        edited = api.put('/dice/me', headers=tokens['Jamie'], json={
            'display_name': 'Shared profile display', 'avatar_url': '/dice/demo-avatars/alpha.webp'})
        assert edited.status_code == 200, edited.text
        assert edited.json()['display_name'] == 'Shared profile display'
        joined = api.get(base, headers=tokens['Jamie']).json()
        repeated = api.post(f'{base}/join', headers=tokens['Jamie'], json={'invite_token': invite})
        assert repeated.status_code == 200 and repeated.json()['revision'] == joined['revision']
        person = joined['members'][1]
        assert person['id'] == guest['id'] and person['user_id'] == jamie_id
        assert person['name'] == 'Source guest name'
        assert person['display_name'] == 'Shared profile display'
        assert person['avatar_url'] == '/dice/demo-avatars/alpha.webp'
        assert api.get('/trips/me', headers=tokens['Jamie']).json()['display_name'] == 'Shared profile display'
        assert api.put('/dice/me', headers=tokens['Jamie'], json={'display_name': 'Updated shared name'}).status_code == 200
        updated = api.get(base, headers=tokens['Matt']).json()
        assert updated['members'][1]['display_name'] == 'Updated shared name'
        assert updated['revision'] == joined['revision']  # Display changes do not rewrite financial records.
        dice = admin.table('dice_profiles').select('display_name,avatar_url').eq('user_id', jamie_id).execute().data
        assert dice == [{'display_name': 'Updated shared name', 'avatar_url': '/dice/demo-avatars/alpha.webp'}]
        raw = admin.table('trips_groups').select('data').eq('id', group_id).execute().data[0]['data']['members'][1]
        assert raw['name'] == 'Source guest name' and 'avatar_url' not in raw
        assert api.get(base, headers=tokens['Alex']).status_code == 404
    finally:
        admin.table('dice_profiles').delete().eq('user_id', jamie_id).execute()
        admin.table('commons_profiles').update(original).eq('user_id', jamie_id).execute()
