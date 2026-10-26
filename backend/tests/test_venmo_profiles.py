from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from venmo import profiles, venmo_client, photos
from venmo.routes import router

FIXTURES = Path(__file__).parent / 'fixtures' / 'venmo'


def test_layers():
    assert profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'ALEX-RIVERA')['source'] == 'live'
    assert profiles.parse_profile((FIXTURES / 'og.html').read_text(), 'alex-rivera')['source'] == 'og'
    assert profiles.parse_profile((FIXTURES / 'garbage.html').read_text(), 'alex-rivera') is None
    assert profiles.parse_profile((FIXTURES / 'untrusted.html').read_text(), 'alex-rivera') is None
    assert profiles.parse_profile((FIXTURES / 'next_missing_user.html').read_text(), 'alex-rivera')['source'] == 'og'


@pytest.mark.parametrize('key,value', [('username', 'someone-else'), ('username', 3), ('displayName', ''), ('displayName', 5), ('initials', None), ('isActive', 'true'), ('profilePictureUrl', 'https://evil.test/a')])
def test_validator(key, value):
    user = dict(username='alex-rivera', displayName='Alex Rivera', initials='AR', isActive=True, profilePictureUrl='https://pics-v3.venmo.com/a')
    user[key] = value
    with pytest.raises(ValueError):
        profiles.validate_user(user, 'alex-rivera')


@pytest.mark.parametrize('url', ['http://pics-v3.venmo.com/a', 'https://pics-v3.venmo.com.evil/a', 'https://user@pics-v3.venmo.com/a', 'https://pics-v3.venmo.com:443/a', 'https://pics-v3.venmo.com:80/a'])
def test_host(url):
    assert profiles.photo_url(url) is None


def test_keeps_venmo_size_and_version():
    # Venmo's host returns 502 for any size or version other than the one in the profile.
    assert profiles.photo_url('https://pics-v3.venmo.com/a?width=460&height=460&version=5&x=1') == 'https://pics-v3.venmo.com/a?width=460&height=460&version=5'
    assert profiles.photo_url('https://pics-v3.venmo.com/a?width=99999&version=abc') == 'https://pics-v3.venmo.com/a'


def test_breaker_and_bucket():
    now = [0]
    breaker = venmo_client.CircuitBreaker(clock=lambda: now[0])
    for _ in range(5):
        assert breaker.enter()
        breaker.finish(False)
    assert not breaker.enter()
    now[0] = 600
    assert breaker.enter()
    assert not breaker.enter()
    breaker.finish(False)
    assert not breaker.enter()
    now[0] = 1200
    assert breaker.enter()
    breaker.finish(True)
    assert breaker.enter()
    bucket = venmo_client.TokenBucket(clock=lambda: now[0])
    assert all(bucket.take() for _ in range(5))
    assert not bucket.take()
    now[0] += 1
    assert bucket.take()
    assert not bucket.take()


def test_jitter():
    for _ in range(100):
        assert 86400 * .9 <= profiles.ttl(True) <= 86400 * 1.1
        assert 3600 * .9 <= profiles.ttl(False) <= 3600 * 1.1


def test_lookup_lkg_and_rate_limit(monkeypatch):
    profile = profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'alex-rivera')
    fetch = Mock(side_effect=lambda url, **kw: (b'photo', 'image/png') if kw.get('image') else profile)
    monkeypatch.setattr(venmo_client, 'fetch', fetch)
    photos.cache.clear()
    lookup = profiles.ProfileLookup()
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert fetch.call_count == 2
    lookup.cache['alex-rivera'] = (0, {**profile, 'found': True, 'stale': False})
    fetch.side_effect = RuntimeError('down')
    result = lookup.lookup('alex-rivera', 'qa')
    assert result['found'] and result['stale'] and result['source'] == 'cached'
    lookup.executor.shutdown(wait=True)
    for i in range(40):
        lookup.lookup(f'missing-{i}', 'limited')
    assert fetch.call_count <= 33


@pytest.mark.parametrize('content_type,size,ok', [('image/jpeg', 100, True), ('image/png', 512*1024, True), ('image/webp', 10, True), ('image/svg+xml', 10, False), ('text/html', 10, False), ('image/png', 512*1024+1, False)])
def test_photo_budgets(monkeypatch, content_type, size, ok):
    real_client = httpx.Client
    monkeypatch.setattr(venmo_client.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x'*size, headers={'Content-Type': content_type})), **kw))
    monkeypatch.setattr(venmo_client, 'bucket', venmo_client.TokenBucket(burst=100))
    monkeypatch.setattr(venmo_client, 'breaker', venmo_client.CircuitBreaker())
    if ok:
        assert len(venmo_client.fetch('https://pics-v3.venmo.com/a', image=True, limit=512*1024)[0]) == size
    else:
        with pytest.raises(ValueError):
            venmo_client.fetch('https://pics-v3.venmo.com/a', image=True, limit=512*1024)


def test_auth_and_proxy(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix='/venmo')
    app.state.venmo_supabase = SimpleNamespace(auth=SimpleNamespace(get_user=Mock(return_value=SimpleNamespace(user=SimpleNamespace(id='qa')))))
    profile = {**profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'alex-rivera'), 'found': True}
    monkeypatch.setattr('venmo.routes.lookup.lookup', lambda *args: profile)
    monkeypatch.setattr('venmo.routes.thumbnail', lambda p, db: (b'photo', 'image/png'))
    with TestClient(app) as api:
        assert api.get('/venmo/profile?handle=alex-rivera').status_code == 401
        assert api.get('/venmo/photo?handle=alex-rivera').status_code == 401
        response = api.get('/venmo/photo?handle=alex-rivera', headers={'Authorization': 'Bearer synthetic'})
        assert response.content == b'photo'
        assert response.headers['cache-control'] == 'private, max-age=21600, immutable'


def test_photo_rejects_before_fetch(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(venmo_client, 'fetch', fetch)
    with pytest.raises(ValueError):
        photos.thumbnail({'found': True, 'photoUrl': 'https://evil.test/a'})
    fetch.assert_not_called()


def test_signed_thumbnail_paths_are_scoped_and_expire(monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    from venmo import photo_auth
    now = [1000]
    monkeypatch.setattr(photo_auth.time, 'time', lambda: now[0])
    path = photo_auth.signed_path('alex-rivera', 'qa')
    params = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
    params['expires'] = int(params['expires'])
    assert photo_auth.authorized(**params)
    assert not photo_auth.authorized(**{**params, 'handle': 'other-person'})
    assert not photo_auth.authorized(**{**params, 'sig': 'invalid'})
    now[0] = params["expires"] + 1
    assert not photo_auth.authorized(**params)


@pytest.mark.parametrize('data,key', [({}, 'props'), ({'props': []}, 'props.pageProps'), ({'props': {'pageProps': {}}}, 'props.pageProps.user'), ({'props': {'pageProps': {'user': []}}}, 'props.pageProps.user')])
def test_parser_names_missing_or_mistyped_paths(data, key):
    profile, failures = profiles.parse_layers('<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>', 'alex-rivera')
    assert profile is None
    assert key in failures['next']


def test_stable_versioned_urls(monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    from venmo import photo_auth
    now = [21600 + 50]
    monkeypatch.setattr(photo_auth.time, 'time', lambda: now[0])
    path = photo_auth.signed_path('alex', 'qa', 'photo-a')
    now[0] += 1000
    assert path == photo_auth.signed_path('alex', 'qa', 'photo-a')
    assert path != photo_auth.signed_path('alex', 'qa', 'photo-b')
    params = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
    params['expires'] = int(params['expires'])
    assert now[0] <= params['expires'] <= now[0] + 43200
    assert photo_auth.authorized(**params)
    for changes in ({'user': 'other'}, {'v': 'tampered'}, {'expires': params['expires'] + 1}):
        assert not photo_auth.authorized(**{**params, **changes})
    now[0] = 43200
    assert path != photo_auth.signed_path('alex', 'qa', 'photo-a')
    now[0] = params['expires']
    assert photo_auth.authorized(**params)
    now[0] += 1
    assert not photo_auth.authorized(**params)
    future = now[0] + 43201
    assert not photo_auth.authorized('alex', 'qa', future, photo_auth.signature('alex', 'qa', future, params['v']), params['v'])


def test_durable_photo_and_refresh_prefetch(monkeypatch):
    import base64
    profile = profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'alex-rivera')
    stored = {}
    class Query:
        def __init__(self, table):
            self.table = table
            self.filters = {}
        def select(self, *args):
            return self
        def eq(self, key, value):
            self.filters[key] = value
            return self
        def upsert(self, row):
            stored[self.table] = row
            return self
        def execute(self):
            row = stored.get(self.table)
            return SimpleNamespace(data=[row] if row and all(row.get(k) == v for k, v in self.filters.items()) else [])
    db = SimpleNamespace(table=Query)
    fetch = Mock(side_effect=lambda url, **kw: (b'synthetic', 'image/png') if kw.get('image') else profile)
    monkeypatch.setattr(venmo_client, 'fetch', fetch)
    photos.cache.clear()
    lookup = profiles.ProfileLookup()
    try:
        result = lookup.refresh('alex-rivera', db)
        assert fetch.call_count == 2
        assert stored['venmo_photos']['body'] == base64.b64encode(b'synthetic').decode()
        assert photos.thumbnail(result, db) == (b'synthetic', 'image/png')
        photos.cache.clear()  # Simulate a new backend process.
        fetch.side_effect = AssertionError('Network forbidden after restart')
        assert photos.thumbnail(result, db) == (b'synthetic', 'image/png')
        assert fetch.call_count == 2
        fetch.side_effect = lambda url, **kw: (b'new', 'image/webp') if kw.get('image') else {**profile, 'photoUrl': 'https://pics-v3.venmo.com/new'}
        lookup.refresh('alex-rivera', db)
        assert stored['venmo_photos']['photo_url'].startswith('https://pics-v3.venmo.com/new')
    finally:
        lookup.executor.shutdown(wait=True)
        photos.cache.clear()


def test_bucket_wait_is_bounded(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(venmo_client.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    bucket = venmo_client.TokenBucket(rate=1, burst=1, clock=lambda: now[0])
    assert bucket.take()
    assert bucket.wait(1)
    assert now[0] == pytest.approx(1)
    bucket.rate = 0
    assert not bucket.wait(1)
    assert now[0] == pytest.approx(2)


def test_profile_cache_header_and_version(monkeypatch):
    from venmo import routes
    app = FastAPI()
    app.include_router(router, prefix='/venmo')
    app.state.venmo_supabase = None
    app.dependency_overrides[routes.current_user] = lambda: SimpleNamespace(id='qa')
    profile = {**profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'alex-rivera'), 'found': True}
    monkeypatch.setattr(routes.lookup, 'lookup', lambda *args: profile)
    monkeypatch.setattr(routes, 'thumbnail', lambda p, db: (b'synthetic', 'image/png'))
    with TestClient(app) as api:
        response = api.get('/venmo/profile?handle=alex-rivera')
        assert response.headers['cache-control'] == 'private, max-age=300'
        assert 'v=' in response.json()['photoUrl']
        image = api.get(response.json()['photoUrl'])
        assert image.content == b'synthetic'
        assert image.headers['cache-control'] == 'private, max-age=21600, immutable'
        profile['photoUrl'] = 'https://pics-v3.venmo.com/changed'
        assert api.get(response.json()['photoUrl']).status_code == 404


def test_fetch_waits_for_token_without_retrying_upstream(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(venmo_client.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    bucket = venmo_client.TokenBucket(rate=1, burst=1, clock=lambda: now[0])
    bucket.take()
    monkeypatch.setattr(venmo_client, 'bucket', bucket)
    breaker = venmo_client.CircuitBreaker()
    monkeypatch.setattr(venmo_client, 'breaker', breaker)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(503)
    real_client = httpx.Client
    monkeypatch.setattr(venmo_client.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        venmo_client.fetch('https://pics-v3.venmo.com/synthetic', image=True, token_wait=1)
    assert now[0] == pytest.approx(1)
    assert len(requests) == 1
    assert breaker.failures == 1
    breaker.failures = 5
    breaker.until = breaker.clock() + 600
    with pytest.raises(venmo_client.Unavailable):
        venmo_client.fetch('https://pics-v3.venmo.com/synthetic', image=True, token_wait=1)
    assert len(requests) == 1
