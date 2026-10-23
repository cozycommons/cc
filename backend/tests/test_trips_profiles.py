"""Canonical profile reuse and the shared Commons application composition."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from trips.profiles import avatar_url, current_profile, render_groups
from tests.test_trips import local_api
from trips.ledger import new_group


class ProfileClient:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def table(self, name):
        assert name == 'dice_profiles'
        return self

    def select(self, columns):
        assert columns == 'user_id,display_name,avatar_url'
        return self

    def in_(self, column, ids):
        assert column == 'user_id'
        self.ids = ids
        self.queries.append(list(ids))
        return self

    def execute(self):
        return SimpleNamespace(data=[row for row in self.rows if row['user_id'] in self.ids])


def test_only_linked_member_ids_are_resolved_and_source_names_are_preserved():
    row = new_group(str(uuid4()), 'owner-1', 'Trip', 'USD', 'Source name')
    row['data']['members'].append({'id': 'unclaimed', 'name': 'Another profile name', 'user_id': None})
    before = deepcopy(row)
    client = ProfileClient([
        {'user_id': 'owner-1', 'display_name': 'Existing Dice name', 'avatar_url': '/avatar.png'},
        {'user_id': 'outsider', 'display_name': 'Another profile name', 'avatar_url': '/private.png'},
    ])
    group = render_groups(client, [row])[0]
    assert client.queries == [['owner-1']]
    assert group['members'][0]['name'] == 'Source name'
    assert group['members'][0]['display_name'] == 'Existing Dice name'
    assert group['members'][0]['avatar_url'] == '/avatar.png'
    assert group['members'][1]['avatar_url'] is None
    assert group['members'][1]['user_id'] is None
    assert row == before


def test_current_account_falls_back_without_creating_a_dice_profile():
    client = ProfileClient([])
    user = SimpleNamespace(id='new-user', user_metadata={'full_name': 'New friend', 'avatar_url': 'https://example.com/avatar.png'})
    profile = current_profile(client, user)
    assert profile == {'user_id': 'new-user', 'display_name': 'New friend',
                       'avatar_url': 'https://example.com/avatar.png', 'profile_source': 'account'}


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
    assert matt['profile_source'] == 'dice'
    assert api.get('/dice/me', headers=tokens['Matt']).json()['user_id'] == matt['user_id']
    jamie = api.get('/trips/me', headers=tokens['Jamie']).json()
    jamie_id = jamie['user_id']
    assert jamie['profile_source'] == 'account'
    assert jamie['display_name'] == 'Jamie'
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
    admin.table('dice_profiles').insert({'user_id': jamie_id, 'display_name': 'Shared profile display',
                                       'avatar_url': '/commons/assets/cozy-plant.svg'}).execute()
    try:
        joined = api.post(f'{base}/join', headers=tokens['Jamie'], json={'invite_token': invite}).json()
        repeated = api.post(f'{base}/join', headers=tokens['Jamie'], json={'invite_token': invite})
        assert repeated.status_code == 200 and repeated.json()['revision'] == joined['revision']
        person = joined['members'][1]
        assert person['id'] == guest['id'] and person['user_id'] == jamie_id
        assert person['name'] == 'Source guest name'
        assert person['display_name'] == 'Shared profile display'
        assert person['avatar_url'] == '/commons/assets/cozy-plant.svg'
        assert api.get('/dice/me', headers=tokens['Jamie']).json()['user_id'] == person['user_id']
        admin.table('dice_profiles').update({'display_name': 'Updated shared name'}).eq('user_id', jamie_id).execute()
        updated = api.get(base, headers=tokens['Matt']).json()
        assert updated['members'][1]['display_name'] == 'Updated shared name'
        assert updated['revision'] == joined['revision']  # Display changes do not rewrite financial records.
        raw = admin.table('trips_groups').select('data').eq('id', group_id).execute().data[0]['data']['members'][1]
        assert raw['name'] == 'Source guest name' and 'avatar_url' not in raw
        assert api.get(base, headers=tokens['Alex']).status_code == 404
    finally:
        admin.table('dice_profiles').delete().eq('user_id', jamie_id).execute()
