"""Tests for login-based ESPN onboarding (disney_login + /onboard/login).

Disney's wire is faked at disney_login's transport seam — no network.
The error-envelope fixtures are the real shapes Disney's jgc API
returns (the bad-credentials body below was captured verbatim from a
live negative probe on 2026-10-25, correlation ids aside).
"""

import email.message
import io
import json
import logging
import os
import urllib.error

import pytest

os.environ.setdefault("ESPN_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import accounts, disney_login, routes
from espn.espn_client import EspnClient

PASSWORD = "Sup3r-Secret-Pass!"

BAD_CREDENTIALS_BODY = json.dumps(
    {
        "data": None,
        "error": {
            "keyCategory": "FAILURE_BY_DESIGN",
            "conversationId": None,
            "correlationId": "corr-1",
            "errors": [
                {
                    "code": "AUTHORIZATION_CREDENTIALS",
                    "category": "FAILURE_BY_DESIGN",
                    "inputName": None,
                    "errorId": "err-1",
                    "timestamp": "2026-10-24T23:22:02.498-0700",
                    "data": None,
                    "developerMessage": None,
                    "content": None,
                }
            ],
        },
    }
)


def _error_body(code):
    return json.dumps(
        {"data": None, "error": {"errors": [{"code": code}]}}
    )


def _headers(*pairs):
    msg = email.message.Message()
    for key, value in pairs:
        msg.add_header(key, value)
    return msg


class FakeResponse:
    def __init__(self, status=200, headers=None, body=""):
        self.status = status
        self.headers = headers if headers is not None else _headers()
        self._body = body.encode() if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(status, body, headers=None):
    return urllib.error.HTTPError(
        "https://registerdisney.go.com", status, "err",
        headers if headers is not None else _headers(),
        io.BytesIO(body.encode() if isinstance(body, str) else body),
    )


@pytest.fixture()
def disney(monkeypatch):
    """Route disney_login's transport to scripted handlers by URL."""
    calls = []
    handlers = {}

    def fake_open(req):
        calls.append(req)
        url = req.full_url
        if "guest/login" in url:
            handler = handlers["login"]
        elif "api-key" in url:
            handler = handlers["api_key"]
        elif "fan.api.espn.com" in url:
            handler = handlers["fan"]
        else:  # pragma: no cover - guard against surprise URLs
            raise AssertionError(f"unexpected URL {url}")
        result = handler(req) if callable(handler) else handler
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(disney_login, "_open", fake_open)
    handlers["api_key"] = FakeResponse(
        200, _headers(("api-key", "KEY-123")), '{"data":null,"error":null}'
    )
    return calls, handlers


def _login_calls(calls):
    return [c for c in calls if "guest/login" in c.full_url]


def _ok_login_response():
    return FakeResponse(
        200,
        _headers(
            ("Set-Cookie", "espn_s2=s2-from-disney; Path=/; Secure"),
            ("Set-Cookie", "SWID={SWID-FROM-DISNEY}; Path=/; Secure"),
        ),
        '{"data":{"sso":{}},"error":null}',
    )


# --- login client --------------------------------------------------------------


def test_login_success_returns_cookies_with_exactly_one_attempt(disney):
    calls, handlers = disney
    handlers["login"] = _ok_login_response()
    cookies = disney_login.login("user@example.com", PASSWORD)
    assert cookies == {"espn_s2": "s2-from-disney", "swid": "{SWID-FROM-DISNEY}"}
    assert len(_login_calls(calls)) == 1
    # the login attempt carried the bootstrap key
    assert _login_calls(calls)[0].headers.get("Authorization") == "APIKEY KEY-123"


def test_login_bad_password_is_invalid_credentials_one_attempt(disney):
    calls, handlers = disney
    handlers["login"] = _http_error(400, BAD_CREDENTIALS_BODY)
    with pytest.raises(disney_login.InvalidCredentialsError) as excinfo:
        disney_login.login("user@example.com", PASSWORD)
    assert len(_login_calls(calls)) == 1
    assert PASSWORD not in str(excinfo.value)


def test_login_failure_logs_disney_code_but_never_secrets(disney, caplog):
    _, handlers = disney
    handlers["login"] = _http_error(400, BAD_CREDENTIALS_BODY)
    with caplog.at_level(logging.INFO, logger="espn.disney_login"):
        with pytest.raises(disney_login.InvalidCredentialsError):
            disney_login.login("user@example.com", PASSWORD)
    assert "AUTHORIZATION_CREDENTIALS" in caplog.text
    assert "InvalidCredentialsError" in caplog.text
    assert PASSWORD not in caplog.text
    assert "KEY-123" not in caplog.text


def test_login_success_logs_no_cookie_values(disney, caplog):
    _, handlers = disney
    handlers["login"] = _ok_login_response()
    with caplog.at_level(logging.INFO, logger="espn.disney_login"):
        disney_login.login("user@example.com", PASSWORD)
    assert "guest/login ok" in caplog.text
    assert "s2-from-disney" not in caplog.text
    assert "SWID-FROM-DISNEY" not in caplog.text
    assert PASSWORD not in caplog.text


def test_login_account_not_found(disney):
    _, handlers = disney
    handlers["login"] = _http_error(
        400, _error_body("AUTHORIZATION_ACCOUNT_NOT_FOUND")
    )
    with pytest.raises(disney_login.AccountNotFoundError):
        disney_login.login("ghost@example.com", PASSWORD)


def test_login_challenge_required(disney):
    _, handlers = disney
    handlers["login"] = _http_error(403, _error_body("CHALLENGE_REQUIRED"))
    with pytest.raises(disney_login.ChallengeRequiredError) as excinfo:
        disney_login.login("user@example.com", PASSWORD)
    assert PASSWORD not in str(excinfo.value)


def test_login_locked_account_is_a_challenge(disney):
    _, handlers = disney
    handlers["login"] = _http_error(400, _error_body("ACCOUNT_LOCKED"))
    with pytest.raises(disney_login.ChallengeRequiredError):
        disney_login.login("user@example.com", PASSWORD)


def test_login_unknown_disney_error_is_upstream(disney):
    _, handlers = disney
    handlers["login"] = _http_error(400, _error_body("SOMETHING_NEW"))
    with pytest.raises(disney_login.DisneyLoginError) as excinfo:
        disney_login.login("user@example.com", PASSWORD)
    # upstream, but not one of the specific user-facing outcomes
    assert type(excinfo.value) is disney_login.DisneyLoginError
    assert "SOMETHING_NEW" in str(excinfo.value)
    assert PASSWORD not in str(excinfo.value)


def test_login_api_key_failure_is_upstream_and_no_login_attempt(disney):
    calls, handlers = disney
    handlers["api_key"] = _http_error(500, "boom")
    handlers["login"] = _ok_login_response()
    with pytest.raises(disney_login.DisneyLoginError):
        disney_login.login("user@example.com", PASSWORD)
    assert _login_calls(calls) == []


def test_login_network_failure_is_upstream(disney):
    _, handlers = disney
    handlers["api_key"] = urllib.error.URLError("connection reset")
    with pytest.raises(disney_login.DisneyLoginError) as excinfo:
        disney_login.login("user@example.com", PASSWORD)
    assert PASSWORD not in str(excinfo.value)


def test_login_200_without_cookies_is_upstream(disney):
    _, handlers = disney
    handlers["login"] = FakeResponse(200, _headers(), '{"data":{},"error":null}')
    with pytest.raises(disney_login.DisneyLoginError, match="session cookies"):
        disney_login.login("user@example.com", PASSWORD)


def test_login_rejects_empty_inputs(disney):
    with pytest.raises(disney_login.DisneyLoginError):
        disney_login.login("", PASSWORD)
    with pytest.raises(disney_login.DisneyLoginError):
        disney_login.login("user@example.com", "")


# --- league discovery ------------------------------------------------------------

FAN_PAYLOAD = {
    "preferences": [
        {
            "type": {"id": 9, "code": "fantasy"},
            "metaData": {
                "entry": {
                    "abbrev": "FBA",
                    "seasonId": 2027,
                    "entryId": 1,
                    "entryMetadata": {"teamName": "mr diddles"},
                    "groups": [
                        {"groupId": 1709148631, "groupName": "My 2027 League"}
                    ],
                }
            },
        },
        {
            "type": {"id": 9, "code": "fantasy"},
            "metaData": {
                "entry": {
                    "abbrev": "FFL",
                    "seasonId": 2027,
                    "entryId": 3,
                    "entryMetadata": {"teamName": "Gridiron Gang"},
                    "groups": [{"groupId": 555, "groupName": "Football League"}],
                }
            },
        },
        {
            "type": {"id": 9, "code": "fantasy"},
            "metaData": {
                "entry": {
                    "abbrev": "FBA",
                    "seasonId": 2026,
                    "entryId": 2,
                    "entryMetadata": {"teamName": "Last Year"},
                    "groups": [{"groupId": 777, "groupName": "Old League"}],
                }
            },
        },
        {"type": {"id": 3, "code": "news"}, "metaData": {}},
    ]
}


def test_discover_filters_to_season_basketball(disney):
    _, handlers = disney
    handlers["fan"] = FakeResponse(200, _headers(), json.dumps(FAN_PAYLOAD))
    leagues = disney_login.discover_basketball_leagues("s2", "{SWID-1}", 2027)
    assert leagues == [
        {
            "league_id": 1709148631,
            "name": "My 2027 League",
            "team_id": 1,
            "team_name": "mr diddles",
        }
    ]


def test_discover_404_is_no_leagues(disney):
    _, handlers = disney
    handlers["fan"] = _http_error(404, "nope")
    assert disney_login.discover_basketball_leagues("s2", "{SWID-1}", 2027) == []


def test_discover_server_error_is_upstream(disney):
    _, handlers = disney
    handlers["fan"] = _http_error(503, "down")
    with pytest.raises(disney_login.DisneyLoginError):
        disney_login.discover_basketball_leagues("s2", "{SWID-1}", 2027)


# --- endpoint --------------------------------------------------------------------


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None

    def insert(self, row):
        row = dict(row, id=f"id-{len(self._store) + 1}")
        self._store.append(row)
        self._rows = [row]
        return self

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in (self._rows or self._store) if r.get(k) == v]
        return self

    def update(self, values):
        for r in self._store:
            r.update(values)
        return self

    def execute(self):
        class R:
            data = self._rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []

    def table(self, name):
        assert name == "espn_accounts"
        return FakeTable(self._store)


LEAGUE_PAYLOAD = {
    "id": 1709148631,
    "seasonId": 2027,
    "settings": {"name": "My 2027 League"},
    "teams": [
        {"id": 1, "name": "mr diddles", "owners": ["{SWID-1}"]},
        {"id": 2, "name": "Other Team", "owners": ["{SWID-2}"]},
    ],
}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("ESPN_CREDENTIALS_KEY", Fernet.generate_key().decode())
    db = FakeSupabase()
    app = FastAPI()
    app.include_router(routes.router, prefix="/espn")
    app.state.supabase = db
    routes._ONBOARD_ATTEMPTS.clear()
    monkeypatch.setattr(
        EspnClient, "probe", staticmethod(lambda *a: {})
    )
    monkeypatch.setattr(
        EspnClient,
        "get_league",
        lambda self, views, scoring_period_id=None: LEAGUE_PAYLOAD,
    )
    state = {"leagues": [], "login_error": None}
    monkeypatch.setattr(
        routes.disney_login,
        "login",
        lambda email, pw: (
            (_ for _ in ()).throw(state["login_error"])
            if state["login_error"]
            else {"espn_s2": "s2-x", "swid": "{SWID-1}"}
        ),
    )
    monkeypatch.setattr(
        routes.disney_login,
        "discover_basketball_leagues",
        lambda s2, swid, season: state["leagues"],
    )
    return TestClient(app), db, state


def test_endpoint_with_league_id_echoes_league_and_team(env):
    client, db, _ = env
    r = client.post(
        "/espn/onboard/login",
        json={
            "email": "w@example.com",
            "password": PASSWORD,
            "label": "warner",
            "league_id": 1709148631,
            "season": 2027,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("cce_")
    assert body["league_id"] == 1709148631
    assert body["league_name"] == "My 2027 League"
    assert body["team_name"] == "mr diddles"
    assert body["team_id"] == 1
    assert body["lineup_automation_enabled"] is False
    assert len(db._store) == 1
    assert PASSWORD not in json.dumps(db._store)


def test_endpoint_enable_automation_sets_flag(env):
    client, db, _ = env
    r = client.post(
        "/espn/onboard/login",
        json={
            "email": "w@example.com",
            "password": PASSWORD,
            "league_id": 1709148631,
            "season": 2027,
            "enable_automation": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["lineup_automation_enabled"] is True
    assert db._store[0]["lineup_automation_enabled"] is True


def test_endpoint_single_discovered_league_onboards(env):
    client, db, state = env
    state["leagues"] = [
        {
            "league_id": 1709148631,
            "name": "My 2027 League",
            "team_id": 1,
            "team_name": "mr diddles",
        }
    ]
    r = client.post(
        "/espn/onboard/login",
        json={"email": "w@example.com", "password": PASSWORD, "season": 2027},
    )
    assert r.status_code == 200
    assert r.json()["league_id"] == 1709148631
    assert len(db._store) == 1


def test_endpoint_multiple_leagues_asks_for_a_pick(env):
    client, db, state = env
    state["leagues"] = [
        {"league_id": 111, "name": "League One", "team_id": 1, "team_name": "A"},
        {"league_id": 222, "name": "League Two", "team_id": 4, "team_name": "B"},
    ]
    r = client.post(
        "/espn/onboard/login",
        json={"email": "w@example.com", "password": PASSWORD, "season": 2027},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "league_selection_required"
    assert [entry["league_id"] for entry in body["leagues"]] == [111, 222]
    assert "token" not in body
    assert db._store == []


def test_endpoint_no_league_found(env):
    client, db, state = env
    state["leagues"] = []
    r = client.post(
        "/espn/onboard/login",
        json={"email": "w@example.com", "password": PASSWORD, "season": 2027},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "no_league_found"
    assert db._store == []


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (disney_login.InvalidCredentialsError("x"), 401, "invalid_credentials"),
        (disney_login.AccountNotFoundError("x"), 404, "account_not_found"),
        (disney_login.ChallengeRequiredError("x"), 403, "challenge_required"),
        (disney_login.DisneyLoginError("x"), 502, "disney_unavailable"),
    ],
)
def test_endpoint_login_error_mapping(env, error, status, detail):
    client, db, state = env
    state["login_error"] = error
    r = client.post(
        "/espn/onboard/login",
        json={"email": "w@example.com", "password": PASSWORD, "league_id": 1},
    )
    assert r.status_code == status
    assert r.json()["detail"] == detail
    assert db._store == []


def test_endpoint_requires_email_and_password(env):
    client, _, _ = env
    r = client.post(
        "/espn/onboard/login", json={"email": " ", "password": ""}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "email_and_password_required"
