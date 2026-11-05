"""/account/linked-accounts: connect Beli, Resy and ESPN on the account page instead of pasting a token into an agent."""
import urllib.error
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

import request_validation
from commons_account import routes
from espn import accounts as espn_accounts, disney_login
from espn.espn_client import EspnAuthError, EspnClient, EspnError
from ig_logger.accounts import hash_token
from ig_logger.sinks.beli import accounts
from ig_logger.sinks.beli.beli_client import BeliClient, BeliError, BeliUnauthorized
from resy import accounts as resy_accounts
from resy.resy_client import ResyAuthError, ResyClient, ResyError
from tests import beli_fakes, resy_fakes
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
        self.tables = {'beli_accounts': [], 'resy_accounts': [], 'espn_accounts': [], 'ig_logger_sources': []}
        self.beli_accounts, self.resy_accounts = self.tables['beli_accounts'], self.tables['resy_accounts']
        self.espn_accounts = self.tables['espn_accounts']

    def table(self, name):
        return Rows(self, 'ig_logger_sources' if name not in self.tables else name)

    def rpc(self, name, args):
        if name == 'espn_claim_account_proven':
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=claim_proven(self.espn_accounts, **args)))
        rows = {'beli_link_account': self.beli_accounts, 'resy_link_account': self.resy_accounts,
                'espn_link_account': self.espn_accounts}[name]

        def execute():
            outcome = link_account(rows, **args)
            if name == 'espn_link_account' and outcome == 'linked':  # 0091: an unproven link starts unproven
                next(r for r in rows if r['id'] == args['p_account_id'])['owner_proven'] = False
            return SimpleNamespace(data=outcome)
        return SimpleNamespace(execute=execute)


def claim_proven(rows, p_account_id, p_user_id):
    # Mirrors public.espn_claim_account_proven (0091); the real one also expires pending proposals.
    account = next((row for row in rows if row['id'] == p_account_id), None)
    if account is None:
        return 'missing'
    if account['owner_user_id'] == p_user_id:
        account['owner_proven'] = True
        return 'already_linked'
    if account['owner_user_id'] is not None and account.get('owner_proven'):
        return 'other_owner'
    previous = account['owner_user_id']
    for row in rows:
        if row['owner_user_id'] == p_user_id:
            row['owner_user_id'] = None
    account.update(owner_user_id=p_user_id, owner_proven=True)
    return 'linked' if previous is None else 'taken_over'


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
    request_validation.install(root)  # as main.py does: 422 bodies never echo submitted values
    root.state.mcp_supabase = db
    root.include_router(routes.router, prefix='/account')
    return TestClient(root), db


def connect(client, login, headers=SAM, password=PASSWORD):
    return client.post('/account/linked-accounts/beli', headers=headers, json={'login': login, 'password': password})


def test_a_new_beli_login_creates_and_links_an_account_whose_token_nobody_sees(account_app):
    client, db = account_app
    assert client.get('/account/linked-accounts', headers=SAM).json() == {'beli': None, 'resy': None, 'espn': None}
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


def test_reconnecting_refreshes_the_stored_password(account_app, monkeypatch):
    client, db = account_app
    row, _ = beli_fakes.add_account(db, owner='u-sam')
    row['password_enc'] = accounts.encrypt_secret('old-password')
    monkeypatch.setattr(accounts, '_clients', {})
    cached = BeliClient(row['login'], 'old-password')
    accounts._clients[row['id']] = (0, cached)
    assert connect(client, row['login']).json()['status'] == 'already_linked'
    assert accounts.decrypt_secret(row['password_enc']) == PASSWORD
    assert row['id'] not in accounts._clients


def test_linking_a_different_login_drops_the_old_accounts_cached_session(account_app, monkeypatch):
    client, db = account_app
    monkeypatch.setattr(accounts, '_clients', {})
    old_row, _ = beli_fakes.add_account(db, owner='u-sam')
    accounts._clients[old_row['id']] = (0, BeliClient(old_row['login'], 'synthetic-password'))
    assert connect(client, 'new-login@example.test').json()['status'] == 'linked'
    assert old_row['owner_user_id'] is None and old_row['id'] not in accounts._clients


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


# Resy: the same rules, with the email as the login and the Resy session stored beside the password.

@pytest.fixture
def resy_app(account_app, monkeypatch):
    client, db = account_app
    resy_fakes.install(db, monkeypatch)
    db.resy_rejects = set()

    class Session:
        def __init__(self, email):
            self._auth_token = 'resy-session-' + email

    def login_with(email, password):
        db.resy_logins.append(email)
        if db.resy_failure:
            raise db.resy_failure
        if password != PASSWORD or email in db.resy_rejects:
            raise ResyAuthError('Resy rejected the stored credentials')
        return Session(email)
    monkeypatch.setattr(ResyClient, 'login_with', staticmethod(login_with))
    return client, db


def connect_resy(client, login, headers=SAM, password=PASSWORD):
    return client.post('/account/linked-accounts/resy', headers=headers, json={'login': login, 'password': password})


def test_a_new_resy_login_creates_and_links_an_account_whose_token_nobody_sees(resy_app):
    client, db = resy_app
    response = connect_resy(client, 'new@example.test')
    assert response.status_code == 200 and response.json()['status'] == 'linked'
    for secret in ('token', PASSWORD, 'resy-session'):
        assert secret not in response.text
    row, = db.resy_accounts
    assert row['owner_user_id'] == 'u-sam' and row['token_hash'] and row['token_prefix'].startswith('ccr_')
    assert resy_accounts.decrypt_secret(row['password_enc']) == PASSWORD
    assert resy_accounts.decrypt_secret(row['auth_token_enc']) == 'resy-session-new@example.test'
    linked = client.get('/account/linked-accounts', headers=SAM).json()
    assert linked['resy'] == {'id': row['id'], 'label': 'resy'} and linked['beli'] is None


def test_a_legacy_resy_account_is_claimed_by_its_email_and_keeps_its_token(resy_app):
    client, db = resy_app
    row, token = resy_fakes.add_account(db)
    response = connect_resy(client, '  ' + row['email'].upper())
    assert response.json() == {'status': 'linked', 'account': {'id': row['id'], 'label': row['label']}}
    assert len(db.resy_accounts) == 1 and row['owner_user_id'] == 'u-sam'
    assert row['token_hash'] == resy_accounts.hash_token(token)  # the legacy /resy token keeps working
    assert resy_accounts.decrypt_secret(row['email_enc']) == row['email']
    assert connect_resy(client, row['email']).json()['status'] == 'already_linked'


def test_reconnecting_resy_refreshes_the_stored_password_and_session(resy_app):
    client, db = resy_app
    row, _ = resy_fakes.add_account(db, owner='u-sam')
    row['password_enc'] = resy_accounts.encrypt_secret('old-password')
    assert connect_resy(client, row['email']).json()['status'] == 'already_linked'
    assert resy_accounts.decrypt_secret(row['password_enc']) == PASSWORD
    assert resy_accounts.decrypt_secret(row['auth_token_enc']) == 'resy-session-' + row['email']


def test_another_users_resy_account_is_refused_and_untouched(resy_app):
    client, db = resy_app
    row, _ = resy_fakes.add_account(db, owner='u-kim')
    before = (row['password_enc'], row['auth_token_enc'])
    response = connect_resy(client, row['email'])
    assert response.status_code == 409 and 'another Cozy Commons user' in response.json()['detail']
    assert row['owner_user_id'] == 'u-kim' and (row['password_enc'], row['auth_token_enc']) == before


def test_a_wrong_resy_password_or_outage_stores_nothing(resy_app):
    client, db = resy_app
    response = connect_resy(client, 'new@example.test', password='wrong')
    assert response.status_code == 400 and response.json()['detail'] == 'Resy did not accept that email and password.'
    for failure in (ResyError('Resy login -> 503', status=503), TimeoutError('read timed out')):
        db.resy_failure = failure
        response = connect_resy(client, 'new@example.test')
        assert response.status_code == 502 and response.json()['detail'] == 'Resy did not answer. Try again in a minute.'
    assert db.resy_accounts == []


def test_a_resy_login_must_be_an_ascii_email_and_never_echoes_the_password(resy_app):
    client, db = resy_app
    row, _ = resy_fakes.add_account(db)
    kelvin = '\u212a' + row['email'][1:]  # KELVIN SIGN .lower() == 'k'
    assert connect_resy(client, kelvin).status_code == 422
    assert resy_accounts.login_key(kelvin) != resy_accounts.login_key('k' + row['email'][1:])
    response = connect_resy(client, '+1 818 555 1234')
    assert response.status_code == 400 and 'email' in response.json()['detail']
    secret = 'p' * 201
    response = connect_resy(client, 'a@b.test', password=secret)
    assert response.status_code == 400 and secret not in response.text
    response = client.post('/account/linked-accounts/resy', headers={**SAM, 'Content-Type': 'application/json'},
                           content='{"login": 5, "password": "hunter2-secret"}')
    assert response.status_code == 422 and 'hunter2-secret' not in response.text
    assert db.resy_logins == [] and row['owner_user_id'] is None and len(db.resy_accounts) == 1


def test_resy_guesses_are_limited_per_user_and_per_resy_login(resy_app):
    client, db = resy_app
    assert client.post('/account/linked-accounts/resy', json={'login': 'a@b.test', 'password': 'b'}).status_code == 401
    for _ in range(10):
        assert connect_resy(client, 'victim@example.test', password='wrong').status_code == 400
    assert connect_resy(client, 'other@example.test').status_code == 429  # per Commons user
    assert connect_resy(client, 'VICTIM@example.test', headers=KIM, password='wrong').status_code == 429  # per login
    assert connect_resy(client, 'kim@example.test', headers=KIM).status_code == 200


def test_attempts_on_one_service_do_not_block_another(resy_app):
    client, db = resy_app
    for _ in range(10):
        assert connect(client, 'typo@example.test', password='wrong').status_code == 400
    assert connect(client, 'new@example.test').status_code == 429
    assert connect_resy(client, 'new@example.test').status_code == 200


def test_resy_and_beli_links_are_independent(resy_app):
    client, db = resy_app
    assert connect(client, 'same@example.test').status_code == 200
    assert connect_resy(client, 'same@example.test').status_code == 200
    linked = client.get('/account/linked-accounts', headers=SAM).json()
    assert linked['beli']['id'] == db.beli_accounts[0]['id'] and linked['resy']['id'] == db.resy_accounts[0]['id']


# ESPN: a MyDisney login proves the SWID; typed cookies prove only themselves.

SWID = '{0E1D2C3B-SYNTHETIC-SWID}'
LEAGUE = {'league_id': 999, 'name': 'Synthetic League', 'team_name': 'Synthetic Squad', 'team_id': 7}


@pytest.fixture
def espn_app(account_app, monkeypatch):
    client, db = account_app
    monkeypatch.setenv('ESPN_CREDENTIALS_KEY', Fernet.generate_key().decode())
    db.espn_logins, db.espn_probes, db.espn_failure, db.espn_challenge = [], [], None, False
    db.espn_leagues = [LEAGUE]
    db.espn_s2_issued = iter(f'fresh-s2-{n}' for n in range(100))

    def login(email, password):
        db.espn_logins.append(email)
        if db.espn_failure:
            raise db.espn_failure
        if db.espn_challenge:
            raise disney_login.ChallengeRequiredError('verify')
        if email == 'nobody@example.test':
            raise disney_login.AccountNotFoundError('no account')
        if password != PASSWORD:
            raise disney_login.InvalidCredentialsError('bad password')
        return {'espn_s2': next(db.espn_s2_issued), 'swid': SWID}

    def probe(espn_s2, swid, league_id, season):
        db.espn_probes.append((espn_s2, swid, league_id, season))
        if espn_s2 == 'expired-s2':
            raise EspnAuthError('ESPN league: cookies expired', status=401)
        if league_id == 404:
            raise EspnError('ESPN league -> 404', status=404)
        return {'settings': {'name': 'Synthetic League'}}
    monkeypatch.setattr(disney_login, 'login', login)
    monkeypatch.setattr(disney_login, 'discover_basketball_leagues', lambda s2, swid, season: list(db.espn_leagues))
    monkeypatch.setattr(EspnClient, 'probe', staticmethod(probe))
    return client, db


def connect_espn(client, login='sam@example.test', headers=SAM, password=PASSWORD, **extra):
    return client.post('/account/linked-accounts/espn', headers=headers,
                       json={'login': login, 'password': password, **extra})


def connect_cookies(client, espn_s2='typed-s2', swid=SWID, headers=SAM, **extra):
    return client.post('/account/linked-accounts/espn/cookies', headers=headers,
                       json={'league_id': 999, 'season': 2027, 'espn_s2': espn_s2, 'swid': swid, **extra})


def legacy_espn(db, owner=None, espn_s2='legacy-s2', swid=SWID, proven=False):
    token = espn_accounts.mint_token()
    row = {'id': str(uuid4()), 'label': 'legacy', 'league_id': 999, 'season': 2027,
           'espn_s2_enc': espn_accounts.encrypt_secret(espn_s2), 'swid_enc': espn_accounts.encrypt_secret(swid),
           'token_hash': espn_accounts.hash_token(token), 'token_prefix': token[:12],
           'lineup_automation_enabled': True, 'owner_user_id': owner, 'owner_proven': proven}
    db.espn_accounts.append(row)
    return row, token


def stored_s2(row):
    return espn_accounts.decrypt_secret(row['espn_s2_enc'])


def test_an_espn_login_creates_and_links_a_new_account_without_storing_the_password(espn_app):
    client, db = espn_app
    response = connect_espn(client, season=2027, enable_automation=False)
    assert response.status_code == 200, response.text
    assert response.json() == {'status': 'linked', 'account': {'id': db.espn_accounts[0]['id'], 'label': 'espn',
                                                               'league_id': 999, 'season': 2027}}
    for secret in (PASSWORD, 'fresh-s2', 'SYNTHETIC-SWID', 'cce_'):
        assert secret not in response.text
    row, = db.espn_accounts
    assert row['owner_user_id'] == 'u-sam' and row['lineup_automation_enabled'] is False
    assert stored_s2(row) == 'fresh-s2-0' and espn_accounts.decrypt_secret(row['swid_enc']) == SWID
    assert PASSWORD not in repr(row)
    summary = client.get('/account/linked-accounts', headers=SAM).json()['espn']
    assert summary == {'id': row['id'], 'label': 'espn', 'league_id': 999, 'season': 2027}


def test_several_leagues_ask_which_one_and_store_nothing_until_chosen(espn_app):
    client, db = espn_app
    db.espn_leagues = [LEAGUE, {**LEAGUE, 'league_id': 1001, 'name': 'Other League'}]
    response = connect_espn(client, season=2027)
    assert response.json() == {'status': 'league_selection_required', 'season': 2027, 'leagues': [
        {'league_id': 999, 'name': 'Synthetic League', 'team_name': 'Synthetic Squad'},
        {'league_id': 1001, 'name': 'Other League', 'team_name': 'Synthetic Squad'}]}
    assert db.espn_accounts == [] and db.espn_probes == []
    chosen = connect_espn(client, season=2027, league_id=1001)
    assert chosen.json()['account']['league_id'] == 1001 and db.espn_accounts[0]['league_id'] == 1001


def test_an_espn_login_claims_a_legacy_team_and_retires_its_token(espn_app):
    client, db = espn_app
    row, token = legacy_espn(db, swid=SWID.lower().strip('{}'))  # SWID case and braces do not matter
    response = connect_espn(client, season=2027)
    assert response.json()['status'] == 'linked' and response.json()['account']['id'] == row['id']
    assert len(db.espn_accounts) == 1 and row['owner_user_id'] == 'u-sam' and stored_s2(row) == 'fresh-s2-0'
    # The legacy token's holder never proved this SWID, so fresh cookies must not reach them.
    assert row['token_hash'] != espn_accounts.hash_token(token) and row['lineup_automation_enabled'] is True


def test_typed_cookies_never_claim_a_team_that_already_exists(espn_app):
    client, db = espn_app
    row, token = legacy_espn(db)
    for espn_s2 in ('typed-s2', 'legacy-s2'):  # not even with the row's own cookies: cookies prove nothing
        response = connect_cookies(client, espn_s2=espn_s2)
        assert response.status_code == 409 and 'ESPN email and password' in response.json()['detail']
    assert row['owner_user_id'] is None and stored_s2(row) == 'legacy-s2' and len(db.espn_accounts) == 1
    assert row['token_hash'] == espn_accounts.hash_token(token)


def test_refreshing_your_own_team_writes_the_cookies_and_retires_the_token(espn_app):
    client, db = espn_app
    client.app.state.supabase = legacy_cache = SimpleNamespace(cleared=0)
    legacy_cache.clear_cache = lambda: setattr(legacy_cache, 'cleared', legacy_cache.cleared + 1)
    row, token = legacy_espn(db, owner='u-sam')
    assert connect_cookies(client, espn_s2='renewed-s2').json()['status'] == 'already_linked'
    assert stored_s2(row) == 'renewed-s2' and row['token_hash'] != espn_accounts.hash_token(token)
    assert legacy_cache.cleared == 1  # legacy /espn token lookups stop hitting the cached row


def test_a_proven_owner_is_never_displaced(espn_app):
    client, db = espn_app
    row, _ = legacy_espn(db, owner='u-kim', proven=True)
    row['espn_s2_enc'] = 'not-a-fernet-token'  # another user's espn_s2 is never decrypted
    before = dict(row)
    for response in (connect_espn(client, season=2027), connect_cookies(client)):
        assert response.status_code == 409 and 'another Cozy Commons user' in response.json()['detail']
    assert row == before and len(db.espn_accounts) == 1


def test_a_league_mate_cannot_squat_a_team_the_real_owner_proves(espn_app):
    client, db = espn_app
    # Kim can read the league, so Kim's own cookies probe fine with Sam's SWID (mTeam lists it).
    squat = connect_cookies(client, espn_s2='kims-s2', headers=KIM, enable_automation=True)
    assert squat.status_code == 200 and squat.json()['status'] == 'linked'
    row, = db.espn_accounts
    assert row['owner_user_id'] == 'u-kim' and row['owner_proven'] is False
    old_token_hash = row['token_hash']
    assert connect_cookies(client, espn_s2='sams-s2').status_code == 409  # cookies cannot take it back
    taken = connect_espn(client, season=2027, enable_automation=False)
    assert taken.status_code == 200 and taken.json()['status'] == 'taken_over'
    assert row['owner_user_id'] == 'u-sam' and row['owner_proven'] is True
    assert stored_s2(row) == 'fresh-s2-0' and row['token_hash'] != old_token_hash
    assert row['lineup_automation_enabled'] is False  # the squatter's choice does not carry over
    assert connect_cookies(client, espn_s2='kims-s2', headers=KIM).status_code == 409
    assert connect_espn(client, season=2027, headers=KIM).status_code == 409  # proven beats a second login


def test_a_chosen_league_must_be_one_of_the_logins_own_leagues(espn_app):
    client, db = espn_app
    response = connect_espn(client, season=2027, league_id=4242)
    assert response.status_code == 400 and 'not one of your ESPN basketball leagues' in response.json()['detail']
    assert db.espn_accounts == [] and db.espn_probes == []


def test_espn_refusals_and_outages_store_nothing(espn_app):
    client, db = espn_app
    assert connect_espn(client, password='wrong').json()['detail'] == 'ESPN did not accept that email and password.'
    assert connect_espn(client, 'nobody@example.test').json()['detail'] == 'ESPN did not accept that email and password.'
    db.espn_challenge = True
    assert 'verification step' in connect_espn(client).json()['detail']
    db.espn_challenge, db.espn_failure = False, disney_login.DisneyLoginError('Disney 503')
    assert connect_espn(client).status_code == 502
    db.espn_failure = None
    db.espn_leagues = []
    assert 'No ESPN fantasy basketball league' in connect_espn(client, season=2027).json()['detail']
    assert connect_cookies(client, espn_s2='expired-s2').json()['detail'].startswith('ESPN did not accept those cookies')
    response = connect_cookies(client, league_id=404)
    assert response.status_code == 400 and 'no basketball league' in response.json()['detail']
    assert db.espn_accounts == []


def test_espn_secrets_are_never_echoed(espn_app):
    client, db = espn_app
    secret = 'p' * 201
    response = connect_espn(client, password=secret)
    assert response.status_code == 400 and secret not in response.text
    cookie = 's2-' + 'x' * 2000
    response = connect_cookies(client, espn_s2=cookie)
    assert response.status_code == 400 and cookie not in response.text
    for path, body in (('/account/linked-accounts/espn', '{"login": 5, "password": "hunter2-secret"}'),
                       ('/account/linked-accounts/espn/cookies',
                        '{"league_id": "x", "season": 2027, "espn_s2": "hunter2-secret", "swid": "{A}"}')):
        response = client.post(path, headers={**SAM, 'Content-Type': 'application/json'}, content=body)
        assert response.status_code == 422 and 'hunter2-secret' not in response.text, response.text
    assert db.espn_logins == [] and db.espn_probes == []


def test_espn_attempts_are_limited_per_user_per_email_and_per_swid(espn_app):
    client, db = espn_app
    assert client.post('/account/linked-accounts/espn/cookies', json={}).status_code == 401
    for _ in range(10):
        assert connect_espn(client, 'victim@example.test', password='wrong').status_code == 400
    assert connect_cookies(client).status_code == 429  # per Commons user
    assert connect_espn(client, 'VICTIM@example.test', headers=KIM, password='wrong').status_code == 429  # per email
    routes._CONNECT_ATTEMPTS.clear()
    for _ in range(10):
        assert connect_cookies(client, espn_s2='expired-s2').status_code == 400
    assert connect_cookies(client, swid=SWID.lower(), headers=KIM).status_code == 429  # per SWID


SECRET = 'SYNTHETIC-SECRET-VALUE'


def assert_422_hides(client, path, bodies):
    """Missing field, wrong type and extra field: each a 422 that never contains the submitted secret."""
    for body in bodies:
        response = client.post(path, headers=SAM, json=body)
        assert response.status_code == 422 and SECRET not in response.text, (body, response.text)


def test_resy_422s_never_echo_the_password(resy_app):
    client, db = resy_app
    assert_422_hides(client, '/account/linked-accounts/resy', [
        {'password': SECRET},
        {'login': 'sam@example.test', 'password': [SECRET]},
        {'login': 'sam@example.test', 'password': 'x', 'note': SECRET},
    ])
    assert db.resy_logins == []


def test_espn_422s_never_echo_the_password_or_cookies(espn_app):
    client, db = espn_app
    assert_422_hides(client, '/account/linked-accounts/espn', [
        {'password': SECRET},
        {'login': 'sam@example.test', 'password': [SECRET]},
        {'login': 'sam@example.test', 'password': SECRET, 'league_id': 'one'},
        {'login': 'sam@example.test', 'password': 'x', 'note': SECRET},
    ])
    assert_422_hides(client, '/account/linked-accounts/espn/cookies', [
        {'league_id': 999, 'season': 2027, 'espn_s2': SECRET},
        {'league_id': 999, 'season': 2027, 'espn_s2': [SECRET], 'swid': '{A}'},
        {'league_id': 999, 'season': 1999, 'espn_s2': SECRET, 'swid': SECRET},
        {'league_id': 999, 'season': 2027, 'espn_s2': 'x', 'swid': '{A}', 'note': SECRET},
    ])
    assert db.espn_logins == [] and db.espn_probes == []
