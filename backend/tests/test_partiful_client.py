"""Unit tests for the Partiful client: envelopes, auth flow, re-auth.

urllib.request.urlopen is stubbed — no network, no Partiful account needed.
"""

import io
import json
import urllib.error
import urllib.request

import pytest

from partiful import partiful_client
from partiful.partiful_client import (
    PartifulAuthError,
    PartifulClient,
    PartifulError,
    normalize_phone,
)


class FakeHTTPResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(b"{}"))


class StubTransport:
    """Routes stubbed urlopen calls by URL; records every request."""

    def __init__(self, monkeypatch):
        self.requests = []
        self.handlers = {}
        monkeypatch.setattr(urllib.request, "urlopen", self._urlopen)

    def on(self, url_prefix, handler):
        self.handlers[url_prefix] = handler
        return self

    def _urlopen(self, req, timeout=None):
        self.requests.append(req)
        for prefix, handler in self.handlers.items():
            if req.full_url.startswith(prefix):
                return handler(req)
        raise AssertionError(f"unexpected URL: {req.full_url}")


def ok(payload):
    return lambda req: FakeHTTPResponse(payload)


def headers_of(req):
    return {k.lower(): v for k, v in req.header_items()}


def body_of(req):
    return json.loads(req.data.decode("utf-8")) if req.data else None


# --- phone normalization -----------------------------------------------------
def test_normalize_phone_us_10_digit():
    assert normalize_phone("8185551234") == "+18185551234"
    assert normalize_phone("(818) 555-1234") == "+18185551234"


def test_normalize_phone_e164():
    assert normalize_phone("+442071234567") == "+442071234567"
    assert normalize_phone("+18185551234") == "+18185551234"


def test_normalize_phone_rejects_garbage():
    with pytest.raises(PartifulError):
        normalize_phone("123")
    with pytest.raises(PartifulError):
        normalize_phone("")


# --- onboarding --------------------------------------------------------------
def test_send_auth_code_posts_phone(monkeypatch):
    t = StubTransport(monkeypatch).on(
        "https://api.partiful.com/sendAuthCodeTrusted",
        ok({"result": {"data": {}}}),
    )
    PartifulClient.send_auth_code("+18185551234")
    (req,) = t.requests
    assert req.full_url == "https://api.partiful.com/sendAuthCodeTrusted"
    assert body_of(req) == {"data": {"params": {"phoneNumber": "+18185551234"}}}
    assert "authorization" not in headers_of(req)  # no auth needed


def test_verify_auth_code_full_sequence(monkeypatch):
    t = (
        StubTransport(monkeypatch)
        .on(
            "https://api.partiful.com/getLoginToken",
            ok({"result": {"data": {"customToken": "ct-1"}}}),
        )
        .on(
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken",
            ok(
                {
                    "idToken": "jwt-1",
                    "refreshToken": "rt-1",
                    "expiresIn": "3600",
                    "localId": "uid-1",
                }
            ),
        )
        .on(
            "https://api.partiful.com/getMyRsvps",
            ok({"result": {"data": {"events": []}}}),
        )
    )
    creds = PartifulClient.verify_auth_code("+18185551234", "123456")
    assert creds == {"refresh_token": "rt-1", "uid": "uid-1"}

    login_req = t.requests[0]
    assert body_of(login_req)["data"]["params"] == {
        "phoneNumber": "+18185551234",
        "authCode": "123456",
    }
    toolkit_req = t.requests[1]
    assert body_of(toolkit_req) == {"token": "ct-1", "returnSecureToken": True}
    # the probe call carries the fresh JWT
    probe_req = t.requests[2]
    assert headers_of(probe_req)["authorization"] == "Bearer jwt-1"


def test_verify_auth_code_bad_code(monkeypatch):
    StubTransport(monkeypatch).on(
        "https://api.partiful.com/getLoginToken",
        ok({"result": {"data": {}}}),
    )
    with pytest.raises(PartifulError, match="wrong or expired SMS code"):
        PartifulClient.verify_auth_code("+18185551234", "000000")


# --- read calls --------------------------------------------------------------
def _authed_client(**kw):
    return PartifulClient("rt-1", "uid-1", **kw)


def test_call_envelope(monkeypatch):
    t = StubTransport(monkeypatch).on(
        "https://api.partiful.com/getMyRsvps",
        ok({"result": {"data": {"events": [{"id": "e1"}]}}}),
    )
    client = _authed_client()
    client._id_token, client._id_token_exp = "jwt-1", 9e18  # skip refresh
    assert client.call("getMyRsvps", {}) == {"events": [{"id": "e1"}]}
    (req,) = t.requests
    assert body_of(req) == {"data": {"params": {}, "userId": "uid-1"}}
    h = headers_of(req)
    assert h["authorization"] == "Bearer jwt-1"
    assert h["origin"] == "https://partiful.com"
    assert h["referer"] == "https://partiful.com/"


def test_get_published_events_bare_array(monkeypatch):
    StubTransport(monkeypatch).on(
        "https://api.partiful.com/getPublishedEvents",
        ok({"result": {"data": [{"id": "h1"}]}}),
    )
    client = _authed_client()
    client._id_token, client._id_token_exp = "jwt-1", 9e18
    assert client.get_published_events() == [{"id": "h1"}]


def test_call_401_refreshes_once_and_retries(monkeypatch):
    calls = {"n": 0}

    def rsvps(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(req.full_url, 401)
        return FakeHTTPResponse({"result": {"data": {"events": []}}})

    refreshed = []
    t = (
        StubTransport(monkeypatch)
        .on("https://api.partiful.com/getMyRsvps", rsvps)
        .on(
            "https://securetoken.googleapis.com/v1/token",
            ok(
                {
                    "id_token": "jwt-2",
                    "refresh_token": "rt-2",  # rotated
                    "expires_in": "3600",
                    "user_id": "uid-1",
                }
            ),
        )
    )
    client = _authed_client(on_refresh=refreshed.append)
    client._id_token, client._id_token_exp = "jwt-stale", 9e18
    assert client.get_my_rsvps() == []
    assert calls["n"] == 2
    assert refreshed == ["rt-2"]  # rotation persisted via callback
    h = headers_of(t.requests[1])
    assert h["referer"] == "https://partiful.com/"  # required by Google
    # retry carried the fresh JWT
    assert headers_of(t.requests[2])["authorization"] == "Bearer jwt-2"


def test_call_401_twice_raises_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(
        "https://api.partiful.com/getMyRsvps",
        lambda req: (_ for _ in ()).throw(http_error(req.full_url, 401)),
    ).on(
        "https://securetoken.googleapis.com/v1/token",
        ok({"id_token": "jwt-2", "refresh_token": "rt-1", "expires_in": "3600"}),
    )
    client = _authed_client()
    client._id_token, client._id_token_exp = "jwt-stale", 9e18
    with pytest.raises(PartifulAuthError):
        client.get_my_rsvps()


def test_dead_refresh_token_raises_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(
        "https://securetoken.googleapis.com/v1/token",
        lambda req: (_ for _ in ()).throw(http_error(req.full_url, 400)),
    )
    client = _authed_client()
    with pytest.raises(PartifulAuthError, match="re-onboard"):
        client.ensure_id_token()


def test_unexpected_envelope_raises(monkeypatch):
    StubTransport(monkeypatch).on(
        "https://api.partiful.com/getMyRsvps", ok({"nope": True})
    )
    client = _authed_client()
    client._id_token, client._id_token_exp = "jwt-1", 9e18
    with pytest.raises(PartifulError, match="unexpected response envelope"):
        client.get_my_rsvps()
