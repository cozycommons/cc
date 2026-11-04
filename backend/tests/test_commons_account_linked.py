"""/account/linked-accounts: connect Beli on the account page instead of pasting a token into an agent."""
import urllib.error
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from commons_account import routes
from ig_logger.accounts import hash_token
from ig_logger.sinks.beli import accounts
from ig_logger.sinks.beli.beli_client import BeliClient, BeliError, BeliUnauthorized
from tests import beli_fakes
from tests.test_commons_agent_tools import link_account

PASSWORD = 'synthetic-password'


class Rows:
    """beli_accounts and ig_logger_sources with just the calls the connect path makes."""

    def __init__(self, db, table):
        self.db, self.table, self.filters, self.write = db, table, [], None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def insert(self, row):
        self.write = ('insert', dict(row, id=str(uuid4()), owner_user_id=None))
        return self

    def update(self, row):
        self.write = ('update', row)
        return self

    def upsert(self, row, on_conflict=None):
        self.write = ('insert', dict(row))
        return self

    def execute(self):
        rows = self.db.tables[self.table]
        if self.write and self.write[0] == 'insert':
            rows.append(self.write[1])
            return SimpleNamespace(data=[dict(self.write[1])])
        matched = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.write:
            for row in matched:
                row.update(self.write[1])
        return SimpleNamespace(data=[dict(r) for r in matched])


class Database:
    def __init__(self):
        self.users = {'session-sam': SimpleNamespace(id='u-sam', email='sam@example.test'),
                      'session-kim': SimpleNamespace(id='u-kim', email='kim@example.test')}
        self.auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(user=self.users.get(token)))
        self.tables = {'beli_accounts': [], 'ig_logger_sources': []}
        self.beli_accounts = self.tables['beli_accounts']

    def table(self, name):
        return Rows(self, 'ig_logger_sources' if name not in self.tables else name)

    def rpc(self, name, args):
        assert name == 'beli_link_account'
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=link_account(self.beli_accounts, **args)))


SAM = {'Authorization': 'Bearer session-sam'}
KIM = {'Authorization': 'Bearer session-kim'}


@pytest.fixture
def account_app(monkeypatch):
    db = Database()
    beli_fakes.install(db, monkeypatch)
    monkeypatch.setattr(routes, '_CONNECT_ATTEMPTS', {})
    db.beli_rejects = set()

    def probe(beli_id, password):
        if db.beli_failure:
            raise db.beli_failure
        if password != PASSWORD or beli_id in db.beli_rejects:
            raise BeliUnauthorized('unauthorized', status=401)
        return {'uuid': 'beli-' + beli_id}
    monkeypatch.setattr(BeliClient, 'probe_credentials', staticmethod(probe))
    root = FastAPI()
    root.state.mcp_supabase = db
    root.include_router(routes.router, prefix='/account')
    return TestClient(root), db


def connect(client, login, headers=SAM, password=PASSWORD):
    return client.post('/account/linked-accounts/beli', headers=headers, json={'login': login, 'password': password})


def test_a_new_beli_login_creates_and_links_an_account_whose_token_nobody_sees(account_app):
    client, db = account_app
    assert client.get('/account/linked-accounts', headers=SAM).json() == {'beli': None}
    response = connect(client, 'new@example.test')
    assert response.status_code == 200 and response.json()['status'] == 'linked'
    assert 'token' not in response.text and PASSWORD not in response.text
    row, = db.beli_accounts
    assert row['owner_user_id'] == 'u-sam' and row['token_hash'] and row['watcher_opt_in'] is True
    assert accounts.decrypt_secret(row['password_enc']) == PASSWORD
    assert client.get('/account/linked-accounts', headers=SAM).json()['beli']['id'] == row['id']


def test_a_legacy_account_is_claimed_by_its_login_and_keeps_its_token(account_app):
    client, db = account_app
    row, token = beli_fakes.add_account(db)
    response = connect(client, '  ' + row['login'].upper())  # case and spacing do not matter for emails
    assert response.json() == {'status': 'linked', 'account': {'id': row['id'], 'label': row['label']}}
    assert len(db.beli_accounts) == 1 and row['owner_user_id'] == 'u-sam'
    assert row['token_hash'] == hash_token(token)  # the legacy /beli token keeps working
    assert connect(client, row['login']).json()['status'] == 'already_linked'


def test_reconnecting_refreshes_the_stored_password(account_app):
    client, db = account_app
    row, _ = beli_fakes.add_account(db, owner='u-sam')
    row['password_enc'] = accounts.encrypt_secret('old-password')
    assert connect(client, row['login']).json()['status'] == 'already_linked'
    assert accounts.decrypt_secret(row['password_enc']) == PASSWORD


def test_another_users_beli_account_is_refused_and_untouched(account_app):
    client, db = account_app
    row, _ = beli_fakes.add_account(db, owner='u-kim')
    before = row['password_enc']
    response = connect(client, row['login'])
    assert response.status_code == 409 and 'another Cozy Commons user' in response.json()['detail']
    assert row['owner_user_id'] == 'u-kim' and row['password_enc'] == before


def test_a_wrong_password_or_beli_outage_stores_nothing(account_app):
    client, db = account_app
    response = connect(client, 'new@example.test', password='wrong')
    assert response.status_code == 400 and 'did not accept' in response.json()['detail']
    db.beli_failure = BeliError('Beli GET /api/user/logged-in/ -> 503', status=503)
    assert connect(client, 'new@example.test').status_code == 502
    db.beli_failure = urllib.error.URLError(ConnectionRefusedError(61, 'Connection refused'))
    assert connect(client, 'new@example.test').json()['detail'] == 'Beli did not answer. Try again in a minute.'
    assert db.beli_accounts == []


def test_phone_logins_match_regardless_of_formatting(account_app):
    client, db = account_app
    row, _ = beli_fakes.add_account(db)
    row['beli_id_enc'] = accounts.encrypt_secret('+1 (818) 555-1234')
    assert connect(client, '+18185551234').json()['account']['id'] == row['id']


def test_connecting_needs_a_session_and_is_rate_limited(account_app):
    client, db = account_app
    assert client.post('/account/linked-accounts/beli', json={'login': 'a', 'password': 'b'}).status_code == 401
    assert client.post('/account/linked-accounts/beli', headers=SAM,
                       json={'login': 'a', 'password': 'b', 'token': 'x'}).status_code == 422
    codes = [connect(client, 'new@example.test', password='wrong').status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429
    assert connect(client, 'other@example.test', headers=KIM).status_code == 200  # per user and per login


def test_unicode_look_alike_logins_never_match_or_rewrite_another_account(account_app):
    client, db = account_app
    row, _ = beli_fakes.add_account(db)
    before = row['password_enc']
    look_alike = row['login'].replace('s', 'ſ', 1)  # LATIN SMALL LONG S lowercases to nothing ASCII
    kelvin = 'K' + row['login'][1:]  # KELVIN SIGN .lower() == 'k'
    for login in (look_alike, kelvin):
        assert connect(client, login).status_code == 422
    assert accounts.login_key(kelvin) != accounts.login_key('k' + row['login'][1:])
    assert row['owner_user_id'] is None and row['password_enc'] == before and len(db.beli_accounts) == 1


def test_validation_errors_never_echo_the_password(account_app):
    client, _ = account_app
    secret = 'p' * 201
    response = client.post('/account/linked-accounts/beli', headers=SAM, json={'login': 'a@b.test', 'password': secret})
    assert response.status_code == 400 and secret not in response.text
    for body in ('{"login": "a@b.test", "password": "hunter2-secret"', '{"login": 5, "password": "hunter2-secret"}'):
        response = client.post('/account/linked-accounts/beli', headers={**SAM, 'Content-Type': 'application/json'},
                               content=body)
        assert response.status_code == 422 and 'hunter2-secret' not in response.text, response.text


def test_an_undecryptable_row_is_skipped_not_fatal(account_app):
    client, db = account_app
    row, _ = beli_fakes.add_account(db)
    row['beli_id_enc'] = 'not-a-fernet-token'
    assert connect(client, 'new@example.test').json()['status'] == 'linked'
    assert row['owner_user_id'] is None and len(db.beli_accounts) == 2


def test_guesses_against_one_beli_login_are_limited_across_commons_users(account_app):
    client, db = account_app
    for _ in range(10):
        assert connect(client, 'victim@example.test', password='wrong').status_code == 400
    assert connect(client, 'VICTIM@example.test', headers=KIM, password='wrong').status_code == 429
