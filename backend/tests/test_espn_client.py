"""Unit tests for the ESPN Fantasy client: URLs, auth mapping, shapes.

urllib.request.urlopen is stubbed — no network, no real ESPN cookies needed.
"""

import concurrent.futures
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
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": players}))
    client = _client()
    assert client.get_players_for_period(6) == players
    (req,) = t.requests
    assert req.full_url.startswith(LEAGUE_URL + "?")
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
    StubTransport(monkeypatch).on(LEAGUE_URL, ok([]))
    with pytest.raises(EspnError, match="unexpected response"):
        _client().get_players_for_period(6)


def test_lineup_projection_fallback_uses_league_kona(monkeypatch):
    from espn import lineup

    players = [{"player": {"proTeamId": 2, "stats": [
        {"statSourceId": 1, "scoringPeriodId": 6, "appliedTotal": 42}
    ]}}]
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": players}))
    assert lineup._kona_projected_teams(_client(), 6) == ({2}, None)
    assert json.loads(headers_of(t.requests[0])["x-fantasy-filter"])[
        "players"
    ]["filterStatsForScoringPeriodIds"] == {"value": [6]}


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("retry_after,delay", [
    (None, 60), ("12", 12), ("invalid", 60), ("-1", 60),
    ("nan", 60), ("inf", 60),
    ("Thu, 29 Oct 2026 14:02:00 GMT", 120),
])
def test_shared_429_cooldown_defers_another_account_without_sleep(
    monkeypatch, method, retry_after, delay
):
    clock = [100.0]
    sleeps = []
    monkeypatch.setattr(espn_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(espn_client.time, "time", lambda: 1793282400.0)  # 14:00 UTC

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(espn_client.time, "sleep", sleep)
    cooldown = espn_client.RequestCooldown()
    first = EspnClient("synthetic-1", "{ONE}", 111, SEASON, cooldown=cooldown)
    second = EspnClient("synthetic-2", "{TWO}", 222, SEASON, cooldown=cooldown)

    def limited(req):
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        raise urllib.error.HTTPError(req.full_url, 429, "limited", headers, io.BytesIO())

    t = StubTransport(monkeypatch).on(first.league_url(), limited)
    t.on(second.league_url(), ok({"id": 222}))
    with pytest.raises(EspnError) as exc:
        if method == "GET":
            first.get_league(["mTeam"])
        else:
            first._post(first.league_url(), {})
    assert exc.value.status == 429
    assert sleeps == []
    with pytest.raises(EspnError) as exc:
        second.get_league(["mTeam"])
    assert exc.value.status == 429
    assert len(t.requests) == 1
    assert sleeps == []
    clock[0] += delay
    second.get_league(["mTeam"])
    second.get_league(["mTeam"])
    assert sleeps == []


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


# --- shared access pattern: per-account pacing, read cache, coalescing ---------
def test_clients_for_one_account_share_one_pacer():
    assert _client()._pacer is _client()._pacer
    assert _client()._pacer is not _client(swid="{OTHER}")._pacer


def test_cached_reads_hit_espn_once_and_default_reads_always_go(monkeypatch):
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    for _ in range(3):
        assert _client().get_league(["mTeam"], max_age=30) == {"id": LEAGUE_ID}
    assert len(t.requests) == 1
    _client().get_league(["mTeam"])
    _client().get_league(["mTeam"])
    assert len(t.requests) == 3


def test_cached_reads_are_keyed_by_views_filter_and_account(monkeypatch):
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"players": []}))
    _client().get_league(["mTeam"], max_age=30)
    _client().get_league(["mRoster"], max_age=30)
    _client(swid="{OTHER}").get_league(["mTeam"], max_age=30)
    _client().get_league_players_for_period(1, max_age=30)
    _client().get_league_players_for_period(2, max_age=30)
    assert len(t.requests) == 5


def test_cached_payloads_are_not_shared_objects(monkeypatch):
    StubTransport(monkeypatch).on(LEAGUE_URL, ok({"teams": [1]}))
    first = _client().get_league(["mTeam"], max_age=30)
    first["teams"].append(2)
    assert _client().get_league(["mTeam"], max_age=30) == {"teams": [1]}


def test_cached_read_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(espn_client.time, "monotonic", lambda: clock[0])
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    _client().get_league(["mTeam"], max_age=30)
    clock[0] += 29
    _client().get_league(["mTeam"], max_age=30)
    clock[0] += 2
    _client().get_league(["mTeam"], max_age=30)
    assert len(t.requests) == 2


def test_failed_reads_are_not_cached(monkeypatch):
    responses = [fail(500), ok("<html>login</html>"), ok({"id": LEAGUE_ID})]
    t = StubTransport(monkeypatch).on(LEAGUE_URL, lambda req: responses.pop(0)(req))
    with pytest.raises(EspnError):
        _client().get_league(["mTeam"], max_age=30)
    with pytest.raises(EspnAuthError):
        _client().get_league(["mTeam"], max_age=30)
    assert _client().get_league(["mTeam"], max_age=30) == {"id": LEAGUE_ID}
    _client().get_league(["mTeam"], max_age=30)
    assert len(t.requests) == 3


def test_a_write_drops_the_accounts_cached_reads(monkeypatch):
    t = StubTransport(monkeypatch).on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    client = _client()
    t.on(client.transactions_url(), ok({}))
    client.get_league(["mTeam"], max_age=30)
    client.post_lineup_transaction("{M}", 1, 5, [])
    client.get_league(["mTeam"], max_age=30)
    assert [r.get_method() for r in t.requests] == ["GET", "POST", "GET"]


def _hold_leader_until_waiters_join(monkeypatch, waiters, response):
    """Block the one ESPN fetch until ``waiters`` threads wait on it."""
    import threading

    joined = threading.Semaphore(0)

    class CountingFuture(espn_client.Future):
        def result(self, timeout=None):
            joined.release()
            return super().result(timeout)

    monkeypatch.setattr(espn_client, "Future", CountingFuture)

    def held(req):
        for _ in range(waiters):
            assert joined.acquire(timeout=5)
        return response(req)

    return held


def _read_concurrently(n):
    import threading

    results = []

    def read():
        try:
            results.append(_client().get_league(["mTeam"], max_age=30))
        except EspnError as e:
            results.append(e.status)

    threads = [threading.Thread(target=read) for _ in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(5)
    return results


def test_concurrent_identical_reads_share_one_request(monkeypatch):
    held = _hold_leader_until_waiters_join(monkeypatch, 3, ok({"id": LEAGUE_ID}))
    t = StubTransport(monkeypatch).on(LEAGUE_URL, held)
    assert _read_concurrently(4) == [{"id": LEAGUE_ID}] * 4
    assert len(t.requests) == 1


def test_waiters_get_the_leaders_error_and_it_is_not_cached(monkeypatch):
    held = _hold_leader_until_waiters_join(monkeypatch, 3, fail(500))
    t = StubTransport(monkeypatch).on(LEAGUE_URL, held)
    assert _read_concurrently(4) == [500] * 4
    assert len(t.requests) == 1
    monkeypatch.setattr(espn_client, "Future", concurrent.futures.Future)
    t.on(LEAGUE_URL, ok({"id": LEAGUE_ID}))
    assert _client().get_league(["mTeam"], max_age=30) == {"id": LEAGUE_ID}


def test_a_read_in_flight_during_a_write_is_not_stored(monkeypatch):
    client = _client()
    t = StubTransport(monkeypatch)

    def raced(req):
        espn_client._READ_CACHE.invalidate(client._scope)  # a write lands mid-read
        return FakeHTTPResponse({"id": "pre-write"})

    t.on(LEAGUE_URL, raced)
    assert client.get_league(["mTeam"], max_age=30) == {"id": "pre-write"}
    t.on(LEAGUE_URL, ok({"id": "post-write"}))
    assert client.get_league(["mTeam"], max_age=30) == {"id": "post-write"}
    assert len(t.requests) == 2


def test_interactive_clients_share_the_process_429_cooldown(monkeypatch):
    def limited(req):
        raise urllib.error.HTTPError(req.full_url, 429, "limited", {}, io.BytesIO())

    first = EspnClient("synthetic-1", "{ONE}", 111, SEASON)
    second = EspnClient("synthetic-2", "{TWO}", 222, SEASON)
    t = StubTransport(monkeypatch).on(first.league_url(), limited)
    t.on(second.league_url(), ok({"id": 222}))
    with pytest.raises(EspnError):
        first.get_league(["mTeam"])
    with pytest.raises(EspnError) as exc:
        second.get_league(["mTeam"])
    assert exc.value.status == 429
    assert len(t.requests) == 1
