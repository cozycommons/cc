from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from trips import venmo_profile as profiles
from trips.routes import router

FIXTURES = Path(__file__).parent / 'fixtures' / 'venmo'


def test_saved_profile_fixtures():
    result = profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'alex-rivera')
    assert result == dict(handle='alex-rivera', displayName='Alex Rivera',
                         photoUrl='https://pics-v3.venmo.com/synthetic.jpg?width=200&height=200', initials='AR', active=True)
    assert profiles.parse_profile((FIXTURES / 'og.html').read_text(), 'alex-rivera')['displayName'] == 'Alex & Sam'
    assert profiles.parse_profile((FIXTURES / 'garbage.html').read_text(), 'alex-rivera') is None
    assert profiles.parse_profile((FIXTURES / 'untrusted.html').read_text(), 'alex-rivera')['photoUrl'] is None
    assert profiles.parse_profile((FIXTURES / 'next.html').read_text(), 'different-user') is None


@pytest.mark.parametrize('url', ['http://pics-v3.venmo.com/a', 'https://pics-v3.venmo.com.evil/a',
                                     'https://user@pics-v3.venmo.com/a', 'https://pics-v3.venmo.com:443/a'])
def test_photo_allowlist(url):
    assert profiles.photo_url(url) is None


def test_authenticated_endpoint_cache_rate_limit_and_fail_soft(monkeypatch):
    calls = []
    def fetch(request):
        calls.append(request)
        assert 'cookie' not in request.headers
        if request.url.path.endswith('broken-user'):
            raise httpx.ReadTimeout('timeout')
        return httpx.Response(200, text=(FIXTURES / 'next.html').read_text())
    real_client = httpx.Client
    monkeypatch.setattr(profiles.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(fetch), **kwargs))
    monkeypatch.setattr(profiles, 'lookup', profiles.ProfileLookup())
    app = FastAPI()
    app.include_router(router, prefix='/trips')
    app.state.trips_supabase = SimpleNamespace(auth=SimpleNamespace(get_user=Mock(return_value=SimpleNamespace(user=SimpleNamespace(id='test-user')))))
    with TestClient(app) as api:
        assert api.get('/trips/venmo/profile?handle=alex-rivera').status_code == 401
        headers = {'Authorization': 'Bearer synthetic'}
        assert api.get('/trips/venmo/profile?handle=@alex-rivera', headers=headers).json()['found']
        assert api.get('/trips/venmo/profile?handle=alex-rivera', headers=headers).json()['found']
        assert len(calls) == 1
        for _ in range(2):
            assert api.get('/trips/venmo/profile?handle=broken-user', headers=headers).json() == {'found': False}
        assert len(calls) == 2
        assert api.get('/trips/venmo/profile?handle=bad!', headers=headers).json() == {'found': False}
        for i in range(28):
            api.get(f'/trips/venmo/profile?handle=missing-{i}', headers=headers)
        assert api.get('/trips/venmo/profile?handle=uncached-user', headers=headers).json() == {'found': False}
        assert len(calls) == 30
        assert api.get('/trips/venmo/profile?handle=alex-rivera', headers=headers).json()['found']
        assert len(calls) == 30


def test_cache_expiry_and_total_fetch_budget(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(profiles.time, 'monotonic', lambda: clock[0])
    def fetch(request):
        calls.append(request.url.path)
        if request.url.path.endswith('slow-user'):
            clock[0] += 4
        return httpx.Response(200, text=(FIXTURES / 'next.html').read_text())
    real_client = httpx.Client
    monkeypatch.setattr(profiles.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(fetch), **kwargs))
    lookup = profiles.ProfileLookup()
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert not lookup.lookup('missing-user', 'qa')['found']
    clock[0] = 301
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert not lookup.lookup('missing-user', 'qa')['found']
    assert len(calls) == 3
    clock[0] = 86401
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert len(calls) == 4
    assert not lookup.lookup('slow-user', 'qa')['found']
