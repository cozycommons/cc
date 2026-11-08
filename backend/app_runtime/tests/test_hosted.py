import importlib
import json
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app_runtime.core import digest, hostname, proxy_config
from app_runtime.hosted_auth import HostedAuth, LOGIN, SESSION, clean_cookie
from app_runtime.settings import Settings
from app_runtime.tests.test_api import FakeRuntime

OWNER = '10000000-0000-4000-8000-000000000001'
VIEWER = '10000000-0000-4000-8000-000000000002'
OTHER = '10000000-0000-4000-8000-000000000003'
CALLER = 'c' * 64


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    from app_runtime import docker_runtime
    monkeypatch.setattr(docker_runtime, 'Runtime', FakeRuntime)
    for key, value in {'APPS_MODE': 'hosted', 'APPS_DOMAIN': 'example.test',
                       'APPS_SUPABASE_URL': 'https://project.supabase.co',
                       'APPS_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test',
                       'APPS_MCP_OAUTH_CLIENT_ID': '20000000-0000-4000-8000-000000000001',
                       'APPS_RUNTIME_IMAGE': 'cc-apps-runtime:test',
                       'APPS_MANAGER_CALLER_SECRET': CALLER,
                       'APPS_CREATORS': OWNER, 'APPS_STATE': str(tmp_path),
                       'APPS_PROXY_CONFIG': str(tmp_path / 'Caddyfile')}.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop('app_runtime.api', None)
    api = importlib.import_module('app_runtime.api')
    api.store.put({'name': 'trip', 'status': 'running', 'members': {OWNER: 'owner', VIEWER: 'viewer'},
                   'routes': {'default': {'port': 3000, 'public': False, 'viewers': True}},
                   'app_token_hash': digest('app-key')})
    monkeypatch.setattr(api.hosted_auth, 'user', lambda token: {'owner-token': OWNER, 'viewer-token': VIEWER, 'other-token': OTHER}.get(token))
    monkeypatch.setattr(api.hosted_auth, 'can_create', lambda token, user_id: token == 'owner-token' and user_id == OWNER)
    with TestClient(api.app, base_url='https://apps.example.test', follow_redirects=False) as c:
        yield c, api
    sys.modules.pop('app_runtime.api', None)


def bearer(token='owner-token'):
    return {'Authorization': 'Bearer ' + token, 'X-Commons-Apps-Caller': CALLER}


def test_mode_validation_and_no_local_fallback(monkeypatch):
    monkeypatch.setenv('APPS_MODE', 'typo')
    with pytest.raises(ValueError):
        Settings.load()
    monkeypatch.setenv('APPS_MODE', 'hosted')
    with pytest.raises(ValueError):
        Settings.load()


def test_creator_roles_and_cookie_cannot_execute(hosted):
    c, api = hosted
    assert c.post('/api/apps', json={'name': 'new'}, headers=bearer('viewer-token')).status_code == 403
    assert c.post('/api/apps', json={'name': 'new'}, headers=bearer()).status_code == 201
    assert c.put(f'/api/apps/trip/members/{OTHER}', json={'role': 'contributor'}, headers=bearer()).status_code == 200
    assert c.put(f'/api/apps/trip/members/{OWNER}', json={'role': 'contributor'}, headers=bearer('other-token')).status_code == 403
    assert c.get('/api/apps', headers=bearer('app-key')).status_code == 403
    assert c.post('/api/apps', json={'name': 'oops'}, headers={'Authorization': 'Basic b3duZXI6b3duZXItdG9rZW4='}).status_code == 401
    key = api.hosted_auth.new_session('apps.example.test', 'owner-token')
    c.cookies.set(SESSION, key, domain='apps.example.test', path='/')
    assert c.get('/').status_code == 200
    assert c.post('/api/apps', json={'name': 'oops'}).status_code == 401
    assert c.post('/api/apps', json={'name': 'oops'}, headers={**bearer(), 'Origin': 'https://trip.example.test'}).status_code == 403


def test_private_routes_revalidate_membership_and_host(hosted):
    c, api = hosted
    host = 'trip.example.test'
    assert c.get('/authorize/trip/default', headers={'Host': host}).status_code == 303
    assert c.get('/authorize/trip/default', headers={**bearer(), 'Host': 'apps.example.test'}).status_code == 400
    assert c.get('/authorize/trip/default', headers={**bearer('other-token'), 'Host': host}).status_code == 404
    key = api.hosted_auth.new_session(host, 'viewer-token')
    headers = {'Host': host, 'Cookie': f'{SESSION}={key}; app_pref=blue; {LOGIN}=private'}
    response = c.get('/authorize/trip/default', headers=headers)
    assert response.status_code == 204
    assert response.headers['x-commons-app-cookie'] == 'app_pref=blue'
    record = api.store.get('trip'); record['members'].pop(VIEWER); api.store.put(record)
    assert c.get('/authorize/trip/default', headers=headers).status_code == 404
    record['routes']['default']['public'] = True; api.store.put(record)
    assert c.get('/authorize/trip/default', headers={'Host': host}).status_code == 204
    record['routes'] = {}; api.store.put(record)
    assert c.get('/authorize/trip/default', headers=headers).status_code == 404


def test_browser_ticket_host_state_origin_and_replay(hosted):
    c, api = hosted
    host = 'trip.example.test'
    started = c.get('/_commons/login', headers={'Host': host})
    state = started.cookies[LOGIN]
    assert 'Secure' in started.headers['set-cookie'] and 'HttpOnly' in started.headers['set-cookie']
    assert 'Domain=' not in started.headers['set-cookie']
    session = api.hosted_auth.new_session('apps.example.test', 'owner-token')
    response = c.get(f'/_commons/authorize?target={host}&state={state}', headers={'Cookie': f'{SESSION}={session}'})
    assert response.status_code == 307
    ticket = response.headers['location'].split('#')[1]
    assert 'owner-token' not in response.headers['location']
    headers = {'Host': host, 'Origin': 'https://' + host, 'Cookie': f'{LOGIN}={state}'}
    assert c.post('/_commons/session', json={'ticket': ticket}, headers={**headers, 'Origin': 'https://evil.test'}).status_code == 403
    installed = c.post('/_commons/session', json={'ticket': ticket}, headers=headers)
    assert installed.status_code == 204
    assert c.post('/_commons/session', json={'ticket': ticket}, headers=headers).status_code == 401
    app_session = installed.cookies[SESSION]
    assert c.get('/', headers={'Cookie': f'{SESSION}={app_session}'}).status_code == 307
    assert c.get('/authorize/trip/default', headers={'Host': host, 'Cookie': f'{SESSION}={app_session}'}).status_code == 204
    assert c.get('/_commons/login', headers={'Host': 'evil.test', 'X-Forwarded-Host': host}).status_code == 400
    assert c.get('/_commons/authorize?target=evil.test&state=' + state).status_code == 400


def test_ticket_requires_browser_nonce(hosted):
    c, api = hosted
    ticket = api.hosted_auth.tickets.put({'host': 'trip.example.test', 'state': 'secret', 'token': 'owner-token'}, 60)
    assert c.post('/_commons/session', headers={'Host': 'trip.example.test', 'Origin': 'https://trip.example.test'}, json={'ticket': ticket}).status_code == 401


def test_pkce_callback_requires_matching_browser_and_discards_refresh(hosted, monkeypatch):
    c, api = hosted
    start = c.get('/_commons/login')
    assert 'code_challenge_method=s256' in start.headers['location']
    assert c.get('/_commons/callback?code=code', headers={'Cookie': ''}).status_code == 400
    class AuthResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {'access_token': 'owner-token', 'refresh_token': 'never-retain'}
    def post(self, url, **kwargs):
        assert url == 'https://project.supabase.co/auth/v1/token?grant_type=pkce'
        assert len(kwargs['json']['code_verifier']) >= 43
        assert kwargs['json']['auth_code'] == 'code'
        return AuthResponse()
    monkeypatch.setattr('httpx.Client.post', post)
    result = c.get('/_commons/callback?code=code')
    assert result.status_code == 303
    assert 'never-retain' not in str(api.hosted_auth.sessions.entries)
    assert c.get('/_commons/callback?code=code').status_code == 400


def test_expired_or_revoked_supabase_identity_fails_closed(hosted, monkeypatch):
    c, api = hosted
    key = api.hosted_auth.new_session('trip.example.test', 'owner-token')
    monkeypatch.setattr(api.hosted_auth, 'user', lambda _: None)
    assert c.get('/authorize/trip/default', headers={'Host': 'trip.example.test', 'Cookie': f'{SESSION}={key}'}).status_code == 303


def test_hosted_proxy_configuration(hosted):
    c, api = hosted
    config = proxy_config(api.store.all(), api.settings)
    assert 'trip.example.test {' in config
    assert 'auto_https off' not in config
    assert 'apps.example.test {' in config
    assert 'cc-apps-hosted-trip:3000' in config
    assert 'copy_headers X-Commons-App-Cookie' in config
    assert 'header_up -Authorization' in config
    assert 'header_up -X-Commons-App-Cookie' in config
    assert 'http://proxy {' in config
    assert 'localhost:8090' not in config
    assert hostname('trip', 'map', api.settings) == 'trip--map.example.test'
    assert clean_cookie(f'a=b; {SESSION}=x; {SESSION}=y; __Host-commons-other=z; q=r') == 'a=b; q=r'


def test_central_logout_revokes_children_even_when_issuance_races(hosted, monkeypatch):
    import concurrent.futures
    import threading
    c, api = hosted
    auth = api.hosted_auth
    central = auth.new_session('apps.example.test', 'owner-token')
    family = auth.sessions.get(central)['family']
    child = auth.new_session('trip.example.test', 'owner-token', family)
    start = c.get('/_commons/login', headers={'Host': 'trip.example.test'})
    state = start.cookies[LOGIN]
    paused, resume = threading.Event(), threading.Event()
    def slow_user(token):
        paused.set()
        assert resume.wait(timeout=3)
        return OWNER
    monkeypatch.setattr(auth, 'user', slow_user)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(c.get, f'/_commons/authorize?target=trip.example.test&state={state}',
                             headers={'Cookie': f'{SESSION}={central}'})
        assert paused.wait(timeout=3)
        response = c.post('/_commons/logout', headers={'Origin': 'https://apps.example.test', 'Cookie': f'{SESSION}={central}'})
        assert response.status_code == 204
        resume.set()
        result = future.result(timeout=3)
    assert not auth.families.get(family)
    if result.status_code == 307:
        ticket = result.headers['location'].split('#')[1]
        assert c.post('/_commons/session', json={'ticket': ticket}, headers={
            'Host': 'trip.example.test', 'Origin': 'https://trip.example.test', 'Cookie': f'{LOGIN}={state}'}).status_code == 401
    assert c.get('/authorize/trip/default', headers={'Host': 'trip.example.test', 'Cookie': f'{SESSION}={child}'}).status_code == 303


def test_login_budget_bounds_unauthenticated_pending_state(hosted):
    c, api = hosted
    api.hosted_auth.login_budget.maximum = 2
    assert c.get('/_commons/login').status_code == 307
    assert c.get('/_commons/login').status_code == 307
    response = c.get('/_commons/login')
    assert response.status_code == 429
    assert response.headers['retry-after'] == '60'
    assert len(api.hosted_auth.pending.entries) == 2


def test_validation_never_echoes_commands(hosted):
    c, api = hosted
    response = c.post('/api/apps/trip/exec', headers=bearer(), json={'command': 'synthetic-sensitive-command', 'timeout': 'invalid'})
    assert response.status_code == 422
    assert 'synthetic-sensitive-command' not in response.text
    assert '"input"' not in response.text


def test_upstream_auth_has_global_budget_and_concurrency_bound(hosted):
    from fastapi import HTTPException
    c, api = hosted
    auth = HostedAuth(api.settings, api.store)
    auth.auth_budget.maximum = 0
    with pytest.raises(HTTPException) as error:
        auth.user('bad-token')
    assert error.value.status_code == 429
    auth.auth_budget.maximum = 10
    for _ in range(4):
        assert auth.auth_slots.acquire(blocking=False)
    with pytest.raises(HTTPException) as error:
        auth.user('bad-token')
    assert error.value.status_code == 503


@pytest.mark.parametrize('client_id,accepted', [(None, True), ('20000000-0000-4000-8000-000000000001', True), ('20000000-0000-4000-8000-000000000002', False)])
def test_upstream_verified_oauth_tokens_require_official_client(hosted, monkeypatch, client_id, accepted):
    import base64
    c, api = hosted
    auth = HostedAuth(api.settings, api.store)
    class Verified:
        status_code = 200
        def json(self):
            return {'id': OWNER, 'role': 'authenticated', 'is_anonymous': False,
                    'user_metadata': {'client_id': api.settings.mcp_client_id}}
    claims = {'sub': OWNER, 'iss': api.settings.supabase_url + '/auth/v1', 'aud': 'authenticated', 'role': 'authenticated'}
    if client_id is not None:
        claims['client_id'] = client_id
    token = 'header.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.signature'
    def get(self, url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer ' + token
        return Verified()
    monkeypatch.setattr('httpx.Client.get', get)
    assert auth.user(token) == (OWNER if accepted else None)


def test_creator_permission_tracks_live_commons_admin_check(hosted, monkeypatch):
    c, api = hosted
    auth = HostedAuth(api.settings, api.store)
    current = {'admin': True, 'id': OWNER}
    class AdminResponse:
        @property
        def status_code(self):
            return 200 if current['admin'] else 403
        def json(self):
            return {'id': current['id']}
    def get(self, url, **kwargs):
        assert url == 'https://api.example.test/admin/session'
        assert kwargs['headers'] == {'Authorization': 'Bearer owner-token'}
        return AdminResponse()
    monkeypatch.setattr('httpx.Client.get', get)
    assert auth.can_create('owner-token', OWNER)
    current['admin'] = False
    assert not auth.can_create('owner-token', OWNER)
    current['admin'] = True
    current['id'] = OTHER
    assert not auth.can_create('owner-token', OWNER)


def test_app_cookie_cannot_log_out_central_family(hosted):
    c, api = hosted
    auth = api.hosted_auth
    central = auth.new_session('apps.example.test', 'owner-token')
    family = auth.sessions.get(central)['family']
    child = auth.new_session('trip.example.test', 'owner-token', family)
    response = c.post('/_commons/logout', headers={'Origin': 'https://apps.example.test', 'Cookie': f'{SESSION}={child}'})
    assert response.status_code == 204
    assert auth.families.get(family)
    assert auth.sessions.get(central) and auth.sessions.get(child)


def test_private_request_validates_identity_once(hosted, monkeypatch):
    c, api = hosted
    calls = []
    def user(token):
        calls.append(token)
        return OWNER
    monkeypatch.setattr(api.hosted_auth, 'user', user)
    for _ in range(2):
        assert c.get('/authorize/trip/default', headers={**bearer(), 'Host': 'trip.example.test'}).status_code == 204
    assert calls == ['owner-token', 'owner-token']


def test_bearer_needs_backend_caller_secret(hosted):
    c, api = hosted
    assert c.get('/api/apps', headers=bearer()).status_code == 200
    missing = {'Authorization': 'Bearer owner-token'}
    assert c.get('/api/apps', headers=missing).status_code == 401
    assert c.get('/api/apps', headers={**missing, 'X-Commons-Apps-Caller': 'c' * 63 + 'd'}).status_code == 401
    # The in-container capability is not a user bearer and needs no secret.
    assert c.put('/api/apps/trip/routes/web', json={'port': 3001},
                 headers={'Authorization': 'Bearer app-key'}).status_code == 200


def test_private_routes_default_to_contributors(hosted):
    c, api = hosted
    host = 'trip--dev.example.test'
    record = api.store.get('trip'); record['members'][OTHER] = 'contributor'
    record['routes']['dev'] = {'port': 5173, 'public': False}; api.store.put(record)
    def status(token):
        key = api.hosted_auth.new_session(host, token)
        return c.get('/authorize/trip/dev', headers={'Host': host, 'Cookie': f'{SESSION}={key}'}).status_code
    assert status('viewer-token') == 403
    assert status('other-token') == 204
    assert status('owner-token') == 204
    assert c.put('/api/apps/trip/routes/dev', json={'port': 5173, 'viewers': True}, headers=bearer()).status_code == 200
    assert status('viewer-token') == 204


def test_another_apps_page_cannot_use_a_members_cookie(hosted):
    c, api = hosted
    host = 'trip.example.test'
    key = api.hosted_auth.new_session(host, 'viewer-token')
    base = {'Host': host, 'Cookie': f'{SESSION}={key}'}
    def status(**headers):
        return c.get('/authorize/trip/default', headers={**base, **headers}).status_code
    assert status(Origin='https://evil.example.test') == 403
    assert status(Origin='https://evil--trip.example.test') == 403
    assert status(Origin='https://trip.evil.example.test') == 403
    assert status(Origin='http://trip.example.test') == 403
    assert status(Origin='null') == 403
    assert status(**{'Sec-Fetch-Site': 'same-site', 'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Dest': 'script'}) == 403
    assert status(**{'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors'}) == 403
    # Same app, own services, same-origin requests and plain navigations work.
    assert status(Origin='https://trip.example.test') == 204
    assert status(Origin='https://trip--api.example.test') == 204
    assert status(**{'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors'}) == 204
    assert status(**{'Sec-Fetch-Site': 'same-site', 'Sec-Fetch-Mode': 'navigate'}) == 204
    assert status() == 204
    # Public routes carry no member identity, so they need no origin check.
    record = api.store.get('trip'); record['routes']['default']['public'] = True; api.store.put(record)
    assert status(Origin='https://evil.example.test') == 204
