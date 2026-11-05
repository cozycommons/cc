"""Account-scoped sessions against a synthetic loopback Beli API."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

import jwt
import pytest

from ig_logger.sinks.beli import accounts, beli_client, sink, mcp_server
from ig_logger.sinks.beli.beli_client import BeliError, BeliUnauthorized
from tests.test_beli_client import Handler, mock_beli


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(accounts, '_clients', {})
    monkeypatch.setattr(beli_client, 'MIN_GAP_S', 0)


def account(key='alice', password='synthetic'):
    return {'id': key, 'beli_id': key + '@example.test', 'password': password}


def paths():
    return [path for path, _, _ in Handler.seen]


def test_repeated_requests_are_isolated_by_account_id(mock_beli):
    alice, bob = account(), account('bob')
    for who in (alice, bob, alice, bob):
        accounts.make_client_for_account(who).api('/api/user/logged-in/')
    assert paths().count('/api/token/') == 2
    sent = [jwt.decode(h['Authorization'][7:], options={'verify_signature': False})['sub']
            for h in Handler.headers_seen if 'Authorization' in h]
    assert sent == [alice['beli_id'], bob['beli_id'], alice['beli_id'], bob['beli_id']]
    # Even duplicate Beli logins in distinct rows never share a client/session.
    duplicate = dict(alice, id='another-row')
    assert accounts.make_client_for_account(duplicate) is not accounts.make_client_for_account(alice)


@pytest.mark.parametrize('field,value', [('password', 'new-password'), ('beli_id', 'new@example.test')])
def test_changed_credentials_evict_session(mock_beli, field, value):
    who = account()
    before = accounts.make_client_for_account(who)
    before.ensure_access_token()
    after = accounts.make_client_for_account(dict(who, **{field: value}))
    assert after is not before
    assert after.user_agent == before.user_agent
    after.ensure_access_token()
    assert paths().count('/api/token/') == 2
    assert Handler.seen[-1][1][field if field == 'password' else 'email'] == value


def test_expiry_and_capacity_evict_sessions(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(accounts, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(accounts, 'MAX_CACHED_SESSIONS', 2)
    first = accounts.make_client_for_account(account())
    now[0] = accounts.SESSION_TTL_S - 1
    assert accounts.make_client_for_account(account()) is first
    now[0] += 1
    second = accounts.make_client_for_account(account())
    assert second is not first  # reuse did not extend the absolute lifetime
    accounts.make_client_for_account(account('bob'))
    accounts.make_client_for_account(account('carol'))
    assert set(accounts._clients) == {'bob', 'carol'}
    assert second.user_agent == first.user_agent


def test_expired_access_refreshes_before_password_login(mock_beli):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    client._access_exp_ms = 0
    accounts.make_client_for_account(account()).api('/api/user/logged-in/')
    assert paths() == ['/api/token/', '/api/token/refresh/', '/api/user/logged-in/']


def test_rejected_refresh_falls_back_once(mock_beli):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    client._access_exp_ms = 0
    Handler.mode = 'bad-refresh'
    client.api('/api/user/logged-in/')
    assert paths() == ['/api/token/', '/api/token/refresh/', '/api/token/', '/api/user/logged-in/']
    # The password login repaired this client, so the next request reuses it: no second login.
    Handler.mode = 'ok'
    accounts.make_client_for_account(account()).api('/api/user/logged-in/')
    assert paths().count('/api/token/') == 2 and accounts.make_client_for_account(account()) is client


def test_refresh_outage_does_not_password_login(mock_beli):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    client._access_exp_ms = 0
    Handler.mode = 'refresh-outage'
    with pytest.raises(BeliError, match='503'):
        client.api('/api/user/logged-in/')
    assert paths() == ['/api/token/', '/api/token/refresh/']
    assert accounts.make_client_for_account(account()) is client


@pytest.mark.parametrize('retry', [False, True])
def test_api_401_keeps_the_client_and_retry_refreshes_first(mock_beli, retry):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    Handler.mode = 'unauthorized-once'
    if retry:
        assert client.api_with_reauth('/api/user/logged-in/') == {'uuid': 'user-1'}
        assert paths().count('/api/token/refresh/') == 1
    else:
        with pytest.raises(BeliUnauthorized):
            client.api('/api/user/logged-in/')
    assert paths().count('/api/token/') == 1
    # The client recovers in place (refresh, then password if needed); evicting it would
    # only force another password login on the next request.
    assert accounts.make_client_for_account(account()) is client
    accounts.make_client_for_account(account()).api('/api/user/logged-in/')
    assert paths().count('/api/token/') == 1


def test_a_rejected_password_login_evicts_only_that_client(mock_beli):
    client = accounts.make_client_for_account(account())
    Handler.mode = 'rejected-login'
    with pytest.raises(BeliUnauthorized):
        client.api('/api/user/logged-in/')
    assert 'alice' not in accounts._clients


def test_a_rotated_refresh_token_is_kept(mock_beli):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    Handler.mode = 'rotate-refresh'
    for _ in range(2):
        client._access_exp_ms = 0
        client.ensure_access_token()
    assert Handler.refreshes_used == ['refresh-1', 'refresh-2']
    assert paths().count('/api/token/') == 1


def test_api_calls_for_one_account_run_in_parallel(mock_beli, monkeypatch):
    client = accounts.make_client_for_account(account())
    client.ensure_access_token()
    inside, release = threading.Barrier(2, timeout=5), threading.Event()
    original = client._request
    def slow_request(host, path, *rest):
        if path == '/api/user/logged-in/':
            inside.wait()  # both calls must be in flight at once, or this times out
        return original(host, path, *rest)
    monkeypatch.setattr(client, '_request', slow_request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.api('/api/user/logged-in/'), range(2)))
    assert results == [{'uuid': 'user-1'}] * 2


def test_old_401_cannot_evict_replacement(mock_beli):
    old = accounts.make_client_for_account(account())
    old.ensure_access_token()
    replacement = accounts.make_client_for_account(account(password='new-password'))
    old._access_exp_ms = 0
    Handler.mode = 'rejected-login'
    old._refresh = None
    with pytest.raises(BeliUnauthorized):
        old.api('/api/user/logged-in/')
    assert accounts.make_client_for_account(account(password='new-password')) is replacement


@pytest.mark.parametrize('refresh', [False, True])
def test_concurrent_requests_do_one_login_or_refresh(mock_beli, monkeypatch, refresh):
    client = accounts.make_client_for_account(account())
    if refresh:
        client.ensure_access_token()
        client._access_exp_ms = 0
    original = client._onboard
    def slow_auth(*args):
        time.sleep(0.03)  # expose the check-then-login race without the session lock
        return original(*args)
    monkeypatch.setattr(client, '_onboard', slow_auth)
    barrier = threading.Barrier(8)
    def request(_):
        barrier.wait(timeout=5)
        shared = accounts.make_client_for_account(account())
        return shared, shared.ensure_access_token()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(8)))
    assert all(shared is client for shared, _ in results)
    assert len({token for _, token in results}) == 1
    assert paths().count('/api/token/') == 1
    assert paths().count('/api/token/refresh/') == int(refresh)


def test_other_accounts_do_not_wait_for_auth(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    alice = accounts.make_client_for_account(account())
    def blocked_login(*_args):
        entered.set()
        assert release.wait(timeout=5)
        return {'access': 'alice-token'}
    monkeypatch.setattr(alice, '_onboard', blocked_login)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(alice.ensure_access_token)
        try:
            assert entered.wait(timeout=5)
            def bob_login():
                bob = accounts.make_client_for_account(account('bob'))
                monkeypatch.setattr(bob, '_onboard', lambda *_: {'access': 'bob-token'})
                return bob.ensure_access_token()
            assert pool.submit(bob_login).result(timeout=2) == 'bob-token'
        finally:
            release.set()
        assert pending.result(timeout=5) == 'alice-token'


def test_sink_and_legacy_mcp_share_account_session(monkeypatch):
    who = account()
    client = accounts.make_client_for_account(who)
    monkeypatch.setattr(accounts, 'decrypt_secret', lambda value: value)
    monkeypatch.setattr(sink, 'candidates_from_caption', lambda _: ['Synthetic Bistro'])
    used = []
    monkeypatch.setattr(sink, 'bookmark_name', lambda shared, *_: used.append(shared) or {'status': 'no_results'})
    sink.BeliSink().process([{'post_caption': 'synthetic'}], {
        'id': who['id'], 'beli_id_enc': who['beli_id'], 'password_enc': who['password']})
    assert used == [client]
    monkeypatch.setenv('SUPABASE_URL', 'http://127.0.0.1:54321')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'synthetic')
    monkeypatch.setattr(mcp_server, 'create_client', lambda *_: object())
    monkeypatch.setattr(accounts, 'get_account_by_token', lambda *_: dict(who))
    assert mcp_server._client_for_token('ccb_synthetic') is client


def test_user_agent_is_stable_on_every_request_and_new_client(mock_beli):
    client = accounts.make_client_for_account(account())
    client.api('/api/user/logged-in/')
    client.api('/api/user/logged-in/')
    assert {h['User-Agent'] for h in Handler.headers_seen} == {client.user_agent}
    assert beli_client.BeliClient(client.beli_id, 'changed', user_agent_key='alice').user_agent == client.user_agent


def test_concurrent_cold_cache_returns_one_client():
    barrier = threading.Barrier(8)
    def lookup(_):
        barrier.wait(timeout=5)
        return accounts.make_client_for_account(account())
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lookup, range(8)))
    assert all(client is clients[0] for client in clients)
