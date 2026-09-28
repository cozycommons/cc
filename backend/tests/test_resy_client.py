"""Unit tests for the Resy client: auth flow, re-login, endpoint shapes.

urllib.request.urlopen is stubbed — no network, no Resy account needed.
"""

import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from resy import resy_client
from resy.resy_client import ResyAuthError, ResyClient, ResyError


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    monkeypatch.setattr(resy_client, "MIN_GAP_S", 0)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("RESY_API_KEY", "test-public-key")


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


def form_of(req):
    return dict(urllib.parse.parse_qsl(req.data.decode("utf-8"))) if req.data else {}


# --- api key -----------------------------------------------------------------
def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("RESY_API_KEY")
    with pytest.raises(ResyError, match="RESY_API_KEY"):
        ResyClient()


def test_headers_carry_public_key(monkeypatch):
    t = StubTransport(monkeypatch).on(
        "https://api.resy.com/4/find", ok({"results": {"venues": []}})
    )
    c = ResyClient()
    c.search("", 40.7, -73.9, "2026-09-28", 2)
    (req,) = t.requests
    h = headers_of(req)
    assert h["authorization"] == 'ResyAPI api_key="test-public-key"'
    assert h["origin"] == "https://resy.com"


# --- login -------------------------------------------------------------------
def test_login_with_posts_form_and_probes(monkeypatch):
    t = (
        StubTransport(monkeypatch)
        .on("https://api.resy.com/3/auth/password", ok({"token": "tok-1"}))
        .on("https://api.resy.com/2/user", ok({"first_name": "Warner"}))
    )
    c = ResyClient.login_with("w@example.com", "pw")
    assert c._auth_token == "tok-1"
    login_req = t.requests[0]
    assert login_req.get_method() == "POST"
    assert form_of(login_req) == {"email": "w@example.com", "password": "pw"}
    # the auth token rides on subsequent calls
    assert headers_of(t.requests[1])["x-resy-auth-token"] == "tok-1"
    assert headers_of(t.requests[1])["x-resy-universal-auth"] == "tok-1"


def test_login_rejects_bad_credentials(monkeypatch):
    def fail(req):
        raise http_error(req.full_url, 401)

    StubTransport(monkeypatch).on("https://api.resy.com/3/auth/password", fail)
    with pytest.raises(ResyAuthError):
        ResyClient.login_with("w@example.com", "wrong")


def test_login_requires_email_and_password(monkeypatch):
    with pytest.raises(ResyError):
        ResyClient.login_with("not-an-email", "pw")
    with pytest.raises(ResyError):
        ResyClient.login_with("w@example.com", "")


# --- 401 -> re-login -> retry -------------------------------------------------
def test_expired_token_relogs_in_once(monkeypatch):
    calls = {"n": 0}

    def flaky(req):
        if req.full_url.startswith("https://api.resy.com/3/auth/password"):
            return FakeHTTPResponse({"token": "tok-2"})
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(req.full_url, 401)
        return FakeHTTPResponse({"results": {"venues": []}})

    StubTransport(monkeypatch).on("https://api.resy.com", flaky)
    c = ResyClient(auth_token="tok-1", email="w@example.com", password="pw")
    c.find_slots(123, "2026-09-28", 2)
    assert c._auth_token == "tok-2"
    # one failed slot call + login probe + one retried slot call — never loops
    assert calls["n"] == 3


def test_dead_credentials_raise_auth_error(monkeypatch):
    def fail(req):
        raise http_error(req.full_url, 401)

    StubTransport(monkeypatch).on("https://api.resy.com", fail)
    c = ResyClient(auth_token="tok-1", email="w@example.com", password="pw")
    with pytest.raises(ResyAuthError, match="rejected the stored credentials"):
        c.find_slots(123, "2026-09-28", 2)


def test_no_stored_credentials_cannot_refresh(monkeypatch):
    def fail(req):
        raise http_error(req.full_url, 401)

    StubTransport(monkeypatch).on("https://api.resy.com", fail)
    c = ResyClient(auth_token="tok-1")  # no email/password
    with pytest.raises(ResyAuthError):
        c.find_slots(123, "2026-09-28", 2)


# --- reads -------------------------------------------------------------------
def test_search_parses_venues(monkeypatch):
    payload = {
        "results": {
            "venues": [
                {
                    "venue": {
                        "id": {"resy": 834},
                        "name": "Lilia",
                        "location": {"neighborhood": "Williamsburg"},
                    },
                    "slots": [
                        {
                            "config": {
                                "id": 1,
                                "type": "Dining Room",
                                "token": "rgs://resy/834/x",
                            },
                            "date": {"start": "2026-09-28 19:00:00", "end": "2026-09-28 20:30:00"},
                        }
                    ],
                }
            ]
        }
    }
    t = StubTransport(monkeypatch).on("https://api.resy.com/4/find", ok(payload))
    c = ResyClient(auth_token="t")
    venues = c.search("lilia", 40.7, -73.9, "2026-09-28", 2)
    assert len(venues) == 1
    assert venues[0]["venue"]["id"]["resy"] == 834
    req = t.requests[0]
    assert "day=2026-09-28" in req.full_url
    assert "party_size=2" in req.full_url


def test_find_slots_venue_scoped(monkeypatch):
    t = StubTransport(monkeypatch).on(
        "https://api.resy.com/4/find",
        ok({"results": {"venues": [{"venue": {"id": {"resy": 834}}, "slots": []}]}}),
    )
    c = ResyClient(auth_token="t")
    assert c.find_slots(834, "2026-09-28", 2) == []
    assert "venue_id=834" in t.requests[0].full_url


def test_get_reservations_pairs_venues(monkeypatch):
    payload = {
        "reservations": [
            {
                "resy_token": "rr://a",
                "reservation_id": 4242,
                "day": "2026-09-28",
                "time_slot": "19:00:00",
                "num_seats": 2,
                "venue": {"id": 834},
                "cancellation": {"allowed": True},
            }
        ],
        "venues": {"834": {"name": "Lilia", "location": {"neighborhood": "Williamsburg"}}},
    }
    StubTransport(monkeypatch).on(
        "https://api.resy.com/3/user/reservations", ok(payload)
    )
    c = ResyClient(auth_token="t")
    (item,) = c.get_reservations()
    assert item["reservation"]["resy_token"] == "rr://a"
    assert item["venue"]["name"] == "Lilia"


# --- booking -----------------------------------------------------------------
def test_book_posts_book_token_and_payment(monkeypatch):
    t = (
        StubTransport(monkeypatch)
        .on(
            "https://api.resy.com/3/details",
            ok({"book_token": {"value": "bt-1"}, "venue": {"name": "Lilia"}}),
        )
        .on(
            "https://api.resy.com/3/book",
            ok({"resy_token": "rr://b", "reservation_id": 99}),
        )
    )
    c = ResyClient(auth_token="t")
    details = c.get_book_details("rgs://resy/834/x", "2026-09-28", 2)
    assert details["book_token"]["value"] == "bt-1"
    result = c.book("bt-1", 12345)
    assert result["resy_token"] == "rr://b"
    book_req = t.requests[1]
    form = form_of(book_req)
    assert form["book_token"] == "bt-1"
    assert json.loads(form["struct_payment_method"]) == {"id": 12345}


def test_cancel_posts_resy_token(monkeypatch):
    t = StubTransport(monkeypatch).on("https://api.resy.com/3/cancel", ok({}))
    c = ResyClient(auth_token="t")
    c.cancel("rr://a")
    assert form_of(t.requests[0]) == {"resy_token": "rr://a"}
