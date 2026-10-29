"""Unit tests for the ESPN Fantasy client: URLs, auth mapping, shapes.

urllib.request.urlopen is stubbed — no network, no real ESPN cookies needed.
"""

import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from espn import espn_client
from espn.espn_client import EspnAuthError, EspnClient, EspnError


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)


class FakeHTTPResponse:
    """Serves a JSON payload, or a raw body when given str/bytes."""

    def __init__(self, payload):
        if isinstance(payload, bytes):
            self._raw = payload
        elif isinstance(payload, str):
            self._raw = payload.encode("utf-8")
        else:
            self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(url, code, body=b"{}"):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


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


def fail(code, body=b"{}"):
    return lambda req: (_ for _ in ()).throw(http_error(req.full_url, code, body))


def headers_of(req):
    return {k.lower(): v for k, v in req.header_items()}


def query_of(req):
    return urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)


ESPN_S2 = "s2-token-abc"
SWID = "{12345678-ABCD-EF00-1234-567890ABCDEF}"
LEAGUE_ID = 1709148631
SEASON = 2027
LEAGUE_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    f"/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
)
PLAYERS_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    f"/seasons/{SEASON}/players"
)


def _client(**kw):
    return EspnClient(kw.get("espn_s2", ESPN_S2), kw.get("swid", SWID),
                      LEAGUE_ID, SEASON)


# --- URL building ------------------------------------------------------------
def test_league_url():
    client = _client()
    assert client.league_url() == LEAGUE_URL
    assert client.league_id == LEAGUE_ID
    assert client.season == SEASON


def test_client_strips_cookie_whitespace(monkeypatch):
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    client = EspnClient(f"  {ESPN_S2}  ", f"  {SWID}\n", LEAGUE_ID, SEASON)
    client.get_league(["mSettings"])
    cookie = headers_of(t.requests[0])["cookie"]
    assert cookie == f"espn_s2={ESPN_S2}; SWID={SWID}"


# --- league reads --------------------------------------------------------------
def test_get_league_repeated_view_params_and_cookie_header(monkeypatch):
    payload = {"id": LEAGUE_ID, "settings": {"name": "Fantasy Hoops '27"},
               "teams": [{"id": 1}]}
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok(payload))
    client = _client()
    assert client.get_league(["mSettings", "mTeam"]) == payload
    (req,) = t.requests
    assert req.full_url.startswith(LEAGUE_URL + "?")
    assert query_of(req) == {"view": ["mSettings", "mTeam"]}
    h = headers_of(req)
    assert h["cookie"] == f"espn_s2={ESPN_S2}; SWID={SWID}"
    assert h["accept"] == "application/json"
    assert "user-agent" in h


def test_get_league_401_raises_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, fail(401))
    with pytest.raises(EspnAuthError, match="re-onboard.*espn_s2/SWID"):
        _client().get_league(["mSettings"])


def test_get_league_403_raises_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, fail(403))
    with pytest.raises(EspnAuthError, match="re-onboard.*espn_s2/SWID"):
        _client().get_league(["mSettings"])


def test_get_league_html_login_page_raises_auth_error(monkeypatch):
    html = (
        "<html><head><title>ESPN Login</title></head>"
        "<body>Please login to continue</body></html>"
    )
    StubTransport(monkeypatch).on(LEAGUE_URL, ok(html))
    with pytest.raises(EspnAuthError, match="re-onboard"):
        _client().get_league(["mSettings"])


def test_get_league_500_raises_error_with_status(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, fail(500, b"upstream boom"))
    with pytest.raises(EspnError) as excinfo:
        _client().get_league(["mSettings"])
    assert excinfo.value.status == 500
    assert not isinstance(excinfo.value, EspnAuthError)
    assert "upstream boom" in str(excinfo.value)


def test_get_league_non_dict_body_raises(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, ok([{"not": "a league"}]))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_league(["mSettings"])


def test_get_league_non_json_body_raises_error_not_auth(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, ok("not json at all"))
    with pytest.raises(EspnError, match="non-JSON") as excinfo:
        _client().get_league(["mSettings"])
    assert not isinstance(excinfo.value, EspnAuthError)


# --- players -------------------------------------------------------------------
def test_get_players_sends_fantasy_filter_and_returns_list(monkeypatch):
    players = [{"id": 1, "player": {"fullName": "Player One"}},
               {"id": 2, "player": {"fullName": "Player Two"}}]
    t = StubTransport(monkeypatch).on(PLAYERS_URL, ok(players))
    client = _client()
    assert client.get_players() == players
    (req,) = t.requests
    assert query_of(req) == {"view": ["kona_player_info"]}
    h = headers_of(req)
    assert h["cookie"] == f"espn_s2={ESPN_S2}; SWID={SWID}"
    fantasy_filter = json.loads(h["x-fantasy-filter"])
    assert fantasy_filter == {
        "players": {
            "limit": 300,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }


def test_get_players_custom_limit(monkeypatch):
    t = StubTransport(monkeypatch).on(PLAYERS_URL, ok([]))
    assert _client().get_players(limit=50) == []
    fantasy_filter = json.loads(headers_of(t.requests[0])["x-fantasy-filter"])
    assert fantasy_filter["players"]["limit"] == 50


def test_get_players_non_list_body_raises(monkeypatch):
    StubTransport(monkeypatch).on(PLAYERS_URL, ok({"players": []}))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_players()


def test_get_players_401_raises_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(PLAYERS_URL, fail(401))
    with pytest.raises(EspnAuthError, match="re-onboard"):
        _client().get_players()


def test_get_players_for_period_filters_stats_to_the_period(monkeypatch):
    players = [
        {
            "id": 1,
            "player": {
                "fullName": "Player One",
                "proTeamId": 2,
                "stats": [
                    {
                        "statSourceId": 1,
                        "scoringPeriodId": 6,
                        "appliedTotal": 42.0,
                    }
                ],
            },
        }
    ]
    t = StubTransport(monkeypatch).on(PLAYERS_URL, ok(players))
    client = _client()
    assert client.get_players_for_period(6) == players
    (req,) = t.requests
    assert query_of(req) == {"view": ["kona_player_info"]}
    fantasy_filter = json.loads(headers_of(req)["x-fantasy-filter"])
    assert fantasy_filter == {
        "players": {
            "filterStatsForScoringPeriodIds": {"value": [6]},
            "limit": 1000,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }


def test_get_players_for_period_non_list_body_raises(monkeypatch):
    StubTransport(monkeypatch).on(PLAYERS_URL, ok({"players": []}))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_players_for_period(6)


# --- league players (league-scoped kona) ---------------------------------------
def test_get_league_players_extracts_players_and_sends_filter(monkeypatch):
    players = [{"id": 1, "onTeamId": 0, "player": {"fullName": "Player One"}},
               {"id": 2, "onTeamId": 3, "player": {"fullName": "Player Two"}}]
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": players}))
    client = _client()
    assert client.get_league_players() == players
    (req,) = t.requests
    assert req.full_url.startswith(LEAGUE_URL + "?")
    assert query_of(req) == {"view": ["kona_player_info"]}
    h = headers_of(req)
    assert h["cookie"] == f"espn_s2={ESPN_S2}; SWID={SWID}"
    fantasy_filter = json.loads(h["x-fantasy-filter"])
    assert fantasy_filter == {
        "players": {
            "limit": 1000,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }


def test_get_league_players_custom_limit(monkeypatch):
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": []}))
    assert _client().get_league_players(limit=2000) == []
    fantasy_filter = json.loads(headers_of(t.requests[0])["x-fantasy-filter"])
    assert fantasy_filter["players"]["limit"] == 2000


def test_get_league_players_non_dict_body_raises(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, ok([{"not": "a league"}]))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_league_players()


def test_get_league_players_missing_players_list_raises(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_league_players()


def test_get_league_players_for_period_filters_stats(monkeypatch):
    players = [
        {
            "id": 1,
            "onTeamId": 0,
            "player": {
                "fullName": "Player One",
                "proTeamId": 2,
                "stats": [
                    {
                        "statSourceId": 0,
                        "statSplitTypeId": 5,
                        "scoringPeriodId": 9,
                        "appliedTotal": 33.0,
                    }
                ],
            },
        }
    ]
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": players}))
    client = _client()
    assert client.get_league_players_for_period(9) == players
    (req,) = t.requests
    assert req.full_url.startswith(LEAGUE_URL + "?")
    assert query_of(req) == {"view": ["kona_player_info"]}
    fantasy_filter = json.loads(headers_of(req)["x-fantasy-filter"])
    assert fantasy_filter == {
        "players": {
            "filterStatsForScoringPeriodIds": {"value": [9]},
            "limit": 1000,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }


# --- probe (onboarding) --------------------------------------------------------
def test_probe_returns_league_payload(monkeypatch):
    payload = {"id": LEAGUE_ID, "settings": {"name": "Fantasy Hoops '27"},
               "teams": []}
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok(payload))
    result = EspnClient.probe(ESPN_S2, SWID, LEAGUE_ID, SEASON)
    assert result == payload
    (req,) = t.requests
    assert query_of(req) == {"view": ["mSettings", "mTeam"]}
    assert headers_of(req)["cookie"] == f"espn_s2={ESPN_S2}; SWID={SWID}"
