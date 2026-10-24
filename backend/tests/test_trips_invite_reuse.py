"""A one-use invite link cannot be claimed by a second account (real local Supabase + API)."""
from uuid import uuid4

from tests.test_trips import local_api  # noqa: F401 - shared fixture


def test_reused_invite_link_is_rejected_for_another_account(local_api):  # noqa: F811
    api, admin, settings, tokens, ids = local_api
    group_id = str(uuid4())
    ids.append(group_id)
    group = api.post('/trips/groups', headers=tokens['Matt'], json={'id': group_id, 'name': 'Invite reuse QA'}).json()
    base = f'/trips/groups/{group_id}'
    added = api.post(f'{base}/members', headers=tokens['Matt'], json={'name': 'One seat', 'revision': group['revision']}).json()
    token = added['invite_token']
    first = api.post(f'{base}/join', headers=tokens['Alex'], json={'invite_token': token})
    assert first.status_code == 200, first.text
    again = api.post(f'{base}/join', headers=tokens['Alex'], json={'invite_token': token})
    assert again.status_code == 200 and again.json()['revision'] == first.json()['revision']  # Harmless repeat for the claimer.
    second = api.post(f'{base}/join', headers=tokens['Jamie'], json={'invite_token': token})
    assert second.status_code == 404, second.text
    assert api.get(base, headers=tokens['Jamie']).status_code == 404
    members = api.get(base, headers=tokens['Matt']).json()['members']
    assert sum(1 for member in members if member['user_id']) == 2  # Matt and Alex only.
