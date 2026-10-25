from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from venmo import profiles, venmo_client

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


def test_size_normalized():
    assert profiles.photo_url('https://pics-v3.venmo.com/a?width=9000&height=9000&x=1') == 'https://pics-v3.venmo.com/a?width=200&height=200'


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
    fetch = Mock(return_value=profile)
    monkeypatch.setattr(venmo_client, 'fetch', fetch)
    lookup = profiles.ProfileLookup()
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert lookup.lookup('alex-rivera', 'qa')['found']
    assert fetch.call_count == 1
    lookup.cache['alex-rivera'] = (0, {**profile, 'found': True, 'stale': False})
    fetch.side_effect = RuntimeError('down')
    result = lookup.lookup('alex-rivera', 'qa')
    assert result['found'] and result['stale'] and result['source'] == 'cached'
    lookup.executor.shutdown(wait=True)
    for i in range(40):
        lookup.lookup(f'missing-{i}', 'limited')
    assert fetch.call_count <= 32








