"""GET /account and PATCH /account/profile: the identity every project header shows."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gotrue.errors import AuthApiError

from commons_account.routes import router
from tests.test_commons_account_profile import Client, account


class SessionClient(Client):
    def __init__(self, **tables):
        super().__init__(accounts=[account(full_name='Google Sam')], **tables)
        users = {'session-sam': account(full_name='Google Sam'),
                 'session-anonymous': SimpleNamespace(id='u2', email=None, user_metadata={}, is_anonymous=True)}

        def get_user(token):
            if token not in users:
                raise AuthApiError('invalid JWT', 401, None)
            return SimpleNamespace(user=users[token])
        self.auth.get_user = get_user


def app(**tables):
    root = FastAPI()
    root.state.mcp_supabase = SessionClient(**tables)
    root.include_router(router, prefix='/account')
    return TestClient(root), root.state.mcp_supabase


SAM = {'Authorization': 'Bearer session-sam'}


def test_first_read_creates_the_profile_and_returns_only_identity_fields():
    client, db = app(dice_profiles=[{'user_id': 'u1', 'display_name': 'Dice Sam', 'avatar_url': None}],
                     commons_profiles=[])
    response = client.get('/account', headers=SAM)
    assert response.status_code == 200
    # Venmo stays out of the header payload; only Trips shows it.
    assert response.json() == {'user_id': 'u1', 'email': 'sam@example.test', 'display_name': 'Dice Sam',
                               'avatar_url': None}
    assert len(db.db['commons_profiles']) == 1


def test_profile_edits_write_the_commons_row_only():
    client, db = app(dice_profiles=[], commons_profiles=[])
    response = client.patch('/account/profile', headers=SAM,
                            json={'display_name': 'Sam H', 'avatar_url': 'https://cdn.test/sam.webp'})
    assert response.status_code == 200
    assert response.json()['display_name'] == 'Sam H'
    assert db.db['commons_profiles'][0]['avatar_url'] == 'https://cdn.test/sam.webp'
    # No Dice row is created: a Trips-only user must not appear on Dice leaderboards.
    assert db.db['dice_profiles'] == []
    assert client.patch('/account/profile', headers=SAM, json={'avatar_url': None}).json()['avatar_url'] is None


def test_profile_edits_refuse_bad_values_and_unknown_fields():
    client, _ = app(dice_profiles=[], commons_profiles=[])
    for body in ({'display_name': ''}, {'display_name': 'x' * 81}, {'avatar_url': 'javascript:alert(1)'},
                 {'venmo_username': 'sam'}, {'user_id': 'u2'}):
        assert client.patch('/account/profile', headers=SAM, json=body).status_code in {400, 422}, body


def test_account_needs_a_real_signed_in_session():
    client, _ = app(commons_profiles=[])
    assert client.get('/account').status_code == 401
    assert client.get('/account', headers={'Authorization': 'Bearer expired'}).status_code == 401
    assert client.get('/account', headers={'Authorization': 'Bearer session-anonymous'}).status_code == 403
    assert client.patch('/account/profile', json={'display_name': 'x'}).status_code == 401
