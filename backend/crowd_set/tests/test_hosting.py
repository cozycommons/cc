import httpx
import pytest
from fastapi.testclient import TestClient

from crowd_set.app import create_app
from crowd_set.hosting import COOKIE
from crowd_set.store import Store


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWD_SET_ORIGIN', 'https://commons.example')
    monkeypatch.setenv('CROWD_SET_AUTH_URL', 'https://test.supabase.co')
    monkeypatch.setenv('CROWD_SET_AUTH_KEY', 'sb_publishable_test')
    monkeypatch.setenv('CROWD_SET_DATA_DIR', str(tmp_path))
    first, second = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
    original = httpx.AsyncClient

    def auth(request):
        assert request.url == 'https://test.supabase.co/auth/v1/user'
        assert request.headers['apikey'] == 'sb_publishable_test'
        token = request.headers['authorization']
        if token == 'Bearer unavailable':
            return httpx.Response(503)
        if token not in ('Bearer first', 'Bearer second', 'Bearer anonymous'):
            return httpx.Response(401)
        return httpx.Response(200, json={'id': first if token == 'Bearer first' else second,
                                       'is_anonymous': token == 'Bearer anonymous', 'email_confirmed_at': '2026-01-01'})

    monkeypatch.setattr('crowd_set.hosting.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(auth), **kwargs))
    # Local files never become publicly owned when a checkout is hosted.
    store = Store(tmp_path)
    store.create('Local only')
    store.close()
    with TestClient(create_app(), base_url='https://commons.example') as api:
        yield api


def test_hosted_auth_origin_cookie_and_owner_isolation(hosted):
    api = hosted
    route = '/crowd-set/sets'
    first = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    second = {'Authorization': 'Bearer second', 'Origin': 'https://commons.example'}
    assert api.get(route).status_code == 401
    assert api.get(route, headers={**first, 'Host': 'evil.example'}).status_code == 403
    assert api.post(route, headers={'Authorization': 'Bearer first'}, json={'name': 'No origin'}).status_code == 403
    assert api.post(route, headers={**first, 'Origin': 'https://evil.example'}, json={'name': 'Bad origin'}).status_code == 403
    assert api.get(route, headers=first).json() == []
    result = api.post(route, headers=first, json={'name': 'Owned'})
    assert result.status_code == 201
    cookie = result.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/crowd-set' in cookie
    path = route + '/' + result.json()['id']
    assert api.get(path).status_code == 200
    assert api.get(path, headers={'Authorization': 'Bearer expired'}).status_code == 401
    assert api.post(path + '/process', headers={'Origin': 'https://commons.example'}).status_code == 401
    for method, suffix in [('GET', ''), ('GET', '/audio'), ('POST', '/process'), ('DELETE', ''),
                           ('PATCH', '/clips/abc'), ('DELETE', '/clips/abc'), ('PUT', '/clips?name=x.wav&role=crowd')]:
        assert api.request(method, path + suffix, headers=second).status_code == 404
    assert api.get(route, headers=second).json() == []
    # A stale first-user cookie never overrides the explicitly supplied second-user token.
    api.cookies.set(COOKIE, 'first', domain='commons.example', path='/crowd-set')
    assert api.get(path + '/audio', headers={**second, 'Range': 'bytes=0-99'}).status_code == 404
    assert api.get(route, headers={'Authorization': 'Bearer anonymous'}).status_code == 403
    assert api.get(route, headers={'Authorization': 'Bearer unavailable'}).status_code == 503
    assert api.delete('/crowd-set/session', headers={'Origin': 'https://commons.example'}).status_code == 204
    assert api.get(route).status_code == 401


def test_hosted_settings_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWD_SET_ORIGIN', 'https://commons.example')
    monkeypatch.delenv('CROWD_SET_AUTH_KEY', raising=False)
    with pytest.raises(RuntimeError, match='requires'):
        create_app(tmp_path)
