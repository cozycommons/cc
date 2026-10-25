"""Public uploads/reads with an in-memory Supabase boundary; no ESPN calls."""

import base64
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import routes, public_predictions, team_claims
from espn.public_predictions import MAX_BODY_BYTES, MAX_LOGO_BYTES, PNG_SIGNATURE

PATH = "/espn/public/predictions"
AUTH = {"Authorization": "Bearer upload-secret"}
SNAPSHOT = {
    "version": "public-v1",
    "generated_at": "2026-10-23T12:00:00Z",
    "captured_at": "2026-10-23T11:00:00Z",
    "names": "abbrev",
    "matchup": {"id": 1, "ends": "2026-10-25"},
    "label": "Uncalibrated model estimates, not betting odds",
    "matchups": [{
        "home": {"name": "HOME"}, "away": {"name": "AWAY"},
        "scores": [100, 90], "projected_totals": [310.5, 300],
        "chance": 60, "range": [50, 70], "margin_80": [-20, 40],
        "days": [{"date": "2026-10-23", "state": "live", "actual": [10, None],
                  "expected": [50, 40], "games": [3, 4]}],
        "odds_history": [{"date": "2026-10-22", "chance": 55}],
    }],
}
PNG_LOGO = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


@pytest.fixture
def snapshot_v2():
    body = copy.deepcopy(SNAPSHOT)
    body["version"] = "public-v2"
    body["teams"] = [
        {"id": 1, "name": "Home", "abbrev": "H", "logo": PNG_LOGO},
        {"id": 2, "name": "Away", "abbrev": "A", "logo": "https://g.espncdn.com/team.svg"},
        {"id": 3, "name": "Other", "abbrev": "O", "logo": None},
    ]
    matchup = body["matchups"][0]
    matchup.update(home=1, away=2)
    day = matchup["days"][0]
    day["players"] = [[{"id": 3202, "name": "Kevin Durant", "points": 10}],
                      [{"id": 0, "name": "Other Player", "points": None}]]
    final = dict(copy.deepcopy(day), date="2026-10-22", state="final",
                 expected=[None, None], games=[None, None])
    projected = dict(copy.deepcopy(day), date="2026-10-24", state="projected", players=None)
    matchup["days"] = [final, day, projected]
    body["season"] = {
        "weeks_remaining": 19, "playoff_teams": 2, "trials": 10000,
        "modes": {mode: [
            {"team": team, "record": [1, 0, 0], "expected_wins": 10.2,
             "playoff_pct": 75, "title_pct": 33.3, "place_pct": [50, 30, 20]}
            for team in (1, 2, 3)
        ] for mode in ("projections", "balanced", "hot")},
        "history": {"balanced": {"1": [
            {"date": "2026-10-22", "playoff_pct": 70},
            {"date": "2026-10-23", "playoff_pct": 75},
        ]}},
        "form_active": False,
    }
    return body


class FakeTable:
    def __init__(self, store):
        self.store = store
        self.rows = []
        self.ordering = []

    def upsert(self, row, *, on_conflict, ignore_duplicates):
        assert on_conflict == "matchup_id,generated_at"
        assert ignore_duplicates is True
        key = (row["matchup_id"], row["generated_at"])
        if not any((r["matchup_id"], r["generated_at"]) == key for r in self.store):
            row = copy.deepcopy(row)
            row["received_at"] = datetime.now(timezone.utc).isoformat()
            self.store.append(row)
            self.rows = [row]
        return self

    def select(self, columns):
        assert columns == "payload"
        self.rows = list(self.store)
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r[column] == value]
        return self

    def order(self, column, desc=False):
        self.ordering.append((column, desc))
        return self

    def limit(self, count):
        for column, desc in reversed(self.ordering):
            self.rows.sort(key=lambda r: r[column], reverse=desc)
        self.rows = self.rows[:count]
        return self

    def execute(self):
        return SimpleNamespace(data=copy.deepcopy(self.rows))


class FakeSupabase:
    def __init__(self):
        self.rows = []

    def table(self, name):
        assert name == "espn_public_predictions"
        return FakeTable(self.rows)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ESPN_PUBLIC_PREDICTIONS_TOKEN", "upload-secret")
    monkeypatch.setattr(team_claims, "_fallback_snapshot", lambda: None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/espn")
    app.state.supabase = FakeSupabase()
    with TestClient(app) as client:
        yield client


def test_disabled_without_token(client, monkeypatch):
    monkeypatch.delenv("ESPN_PUBLIC_PREDICTIONS_TOKEN")
    assert client.post(PATH, json=SNAPSHOT, headers=AUTH).status_code == 503
    monkeypatch.setenv("ESPN_PUBLIC_PREDICTIONS_TOKEN", "")
    assert client.post(PATH, json=SNAPSHOT, headers=AUTH).status_code == 503
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic upload-secret"},
    {"Authorization": "Bearer"},
])
def test_bad_or_missing_token(client, headers):
    assert client.post(PATH, json=SNAPSHOT, headers=headers).status_code == 401
    assert not client.app.state.supabase.rows


def test_upload_latest_and_duplicate_preserves_original(client, monkeypatch):
    assert client.get(PATH + "/latest").status_code == 404
    response = client.post(PATH, json=SNAPSHOT, headers=AUTH)
    assert response.json() == {
        "stored": True, "matchup_id": 1, "generated_at": "2026-10-23T12:00:00+00:00",
    }
    original = copy.deepcopy(client.app.state.supabase.rows)
    duplicate = copy.deepcopy(SNAPSHOT)
    duplicate["label"] = "Do not overwrite"
    duplicate["generated_at"] = "2026-10-23T05:00:00-07:00"
    assert client.post(PATH, json=duplicate, headers=AUTH).json()["stored"] is False
    assert client.app.state.supabase.rows == original
    monkeypatch.delenv("ESPN_PUBLIC_PREDICTIONS_TOKEN")
    latest = client.get(PATH + "/latest")
    assert latest.status_code == 200
    assert latest.json() == SNAPSHOT
    assert latest.headers["cache-control"] == "public, max-age=300"


def test_latest_is_the_newest_upload_and_has_no_public_filters(client):
    for matchup_id, hour in [(1, "13"), (2, "14"), (1, "12")]:
        body = copy.deepcopy(SNAPSHOT)
        body["matchup"]["id"] = matchup_id
        body["generated_at"] = f"2026-10-23T{hour}:00:00Z"
        assert client.post(PATH, json=body, headers=AUTH).status_code == 200
    response = client.get(PATH + "/latest")
    assert response.json()["generated_at"] == "2026-10-23T12:00:00Z"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert client.get(PATH, params={"matchup_id": 1}).status_code in (404, 405)


@pytest.mark.parametrize("field", ["generated_at", "captured_at"])
def test_future_dated_snapshots_are_rejected(client, field):
    body = copy.deepcopy(SNAPSHOT)
    body[field] = "2099-01-01T00:00:00Z"
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize("key,value", [("range", [80.0, 20.0]), ("margin_80", [10.0, -10.0])])
def test_bounds_must_be_low_then_high(client, key, value):
    body = copy.deepcopy(SNAPSHOT)
    body["matchups"][0][key] = value
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


def test_duplicate_or_unordered_days_rejected(client):
    body = copy.deepcopy(SNAPSHOT)
    days = body["matchups"][0]["days"]
    days.append(copy.deepcopy(days[0]))
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


def test_negative_games_rejected(client):
    body = copy.deepcopy(SNAPSHOT)
    body["matchups"][0]["days"][0]["games"] = [-1, 5]
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


def test_unavailable_and_optional_name_mode(client):
    body = copy.deepcopy(SNAPSHOT)
    del body["names"]
    body["matchups"] = [{"home": {"name": "H"}, "away": {"name": "A"}, "unavailable": True}]
    assert client.post(PATH, json=body, headers=AUTH).status_code == 200
    assert client.get(PATH + "/latest").json() == body


@pytest.mark.parametrize("state,ok", [("final", True), ("live", False), ("projected", False)])
def test_unknown_expected_and_games_only_allowed_on_final_days(client, state, ok):
    body = copy.deepcopy(SNAPSHOT)
    day = body["matchups"][0]["days"][0]
    day.update(state=state, expected=[None, None], games=[None, None])
    if state == "final":
        day["actual"] = [100.0, 90.0]
    assert client.post(PATH, json=body, headers=AUTH).status_code == (200 if ok else 422)


@pytest.mark.parametrize("path,key", [
    ([], "league_id"), (["matchup"], "team_id"),
    (["matchups", 0], "player_name"), (["matchups", 0, "home"], "team_id"),
    (["matchups", 0, "away"], "league_id"),
    (["matchups", 0, "days", 0], "player_name"),
    (["matchups", 0, "odds_history", 0], "team_id"),
])
def test_extra_fields_forbidden_at_every_level(client, path, key):
    body = copy.deepcopy(SNAPSHOT)
    target = body
    for part in path:
        target = target[part]
    target[key] = "private-value"
    response = client.post(PATH, json=body, headers=AUTH)
    assert response.status_code == 422
    assert "private-value" not in response.text
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("path,value", [
    (["version"], "private-v1"), (["names"], "players"), (["label"], "x" * 121),
    (["generated_at"], "yesterday"), (["captured_at"], "2026-10-23T11:00:00"),
    (["generated_at"], "1792756800"), (["captured_at"], 1792756800),
    (["matchup", "ends"], "2026-02-30"), (["matchup", "id"], True),
    (["matchup", "id"], 2**63), (["matchups", 0, "home", "name"], "x" * 61),
    (["matchups", 0, "scores"], [1]), (["matchups", 0, "scores"], [1, 2, 3]),
    (["matchups", 0, "scores"], [None, 2]), (["matchups", 0, "chance"], 101),
    (["matchups", 0, "chance"], -1), (["matchups", 0, "chance"], "60"),
    (["matchups", 0, "chance"], True),
    (["matchups", 0, "days", 0, "state"], "scheduled"),
    (["matchups", 0, "days", 0, "expected"], [None, 2]),
    (["matchups", 0, "days", 0, "games"], [None, 2]),
    (["matchups", 0, "days", 0, "games"], [1.5, 2]),
    (["matchups", 0, "days", 0, "games"], [True, 2]),
    (["matchups", 0, "odds_history", 0, "chance"], 101),
    (["matchups", 0, "odds_history", 0, "at"], 1761300000),
    (["matchups", 0, "odds_history", 0, "at"], "2026-10-24T10:00:00"),
    (["matchups"], SNAPSHOT["matchups"] * 21),
    (["matchups", 0, "days"], SNAPSHOT["matchups"][0]["days"] * 15),
    (["matchups", 0, "odds_history"], SNAPSHOT["matchups"][0]["odds_history"] * 201),
])
def test_invalid_values_and_bounds(client, path, value):
    body = copy.deepcopy(SNAPSHOT)
    target = body
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_numbers(client, value):
    body = copy.deepcopy(SNAPSHOT)
    body["matchups"][0]["scores"][0] = value
    assert client.post(PATH, content=json.dumps(body), headers=AUTH).status_code == 422


@pytest.mark.parametrize("unavailable", [False, 1, "true"])
def test_unavailable_requires_boolean_true(client, unavailable):
    body = copy.deepcopy(SNAPSHOT)
    body["matchups"] = [{"home": {"name": "H"}, "away": {"name": "A"},
                         "unavailable": unavailable}]
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize("content", [b"{", b"null", b"[]", b"\xff"])
def test_invalid_json_and_nonobjects(client, content):
    assert client.post(PATH, content=content, headers=AUTH).status_code == 422


@pytest.mark.parametrize("chunked", [False, True])
def test_body_limit_counts_bytes_even_without_content_length(client, chunked):
    content = b" " * MAX_BODY_BYTES + json.dumps(SNAPSHOT).encode()
    if chunked:
        content = iter([content[:MAX_BODY_BYTES], content[MAX_BODY_BYTES:]])
    assert client.post(PATH, content=content, headers=AUTH).status_code == 413
    assert not client.app.state.supabase.rows


def test_valid_boundaries(client):
    body = copy.deepcopy(SNAPSHOT)
    body["label"] = "x" * 120
    entry = body["matchups"][0]
    entry["home"]["name"] = "x" * 60
    entry["chance"] = 0
    entry["days"][0]["actual"] = None
    entry["days"] = [dict(entry["days"][0], date=f"2026-10-{day:02d}") for day in range(1, 15)]
    entry["odds_history"][0]["chance"] = 100
    entry["odds_history"] *= 30
    body["matchups"] *= 20
    assert client.post(PATH, json=body, headers=AUTH).status_code == 200


def test_intraday_odds_points_carry_their_capture_time(client):
    body = copy.deepcopy(SNAPSHOT)
    body["matchups"][0]["odds_history"] = [
        {"date": "2026-10-22", "chance": 50, "at": f"2026-10-22T{hour % 24:02d}:00:00Z"} for hour in range(200)
    ]
    assert client.post(PATH, json=body, headers=AUTH).status_code == 200


def test_body_limit_accepts_exactly_256_kib(client):
    content = json.dumps(SNAPSHOT).encode()
    content += b" " * (MAX_BODY_BYTES - len(content))
    assert client.post(PATH, content=content, headers=AUTH).status_code == 200


def test_v2_upload_stores_and_returns_complete_snapshot(client, snapshot_v2):
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).json()["stored"] is True
    assert client.app.state.supabase.rows[0]["payload"] == snapshot_v2
    assert client.get(PATH + "/latest").json() == public_predictions._external_logos(snapshot_v2)
    duplicate = copy.deepcopy(snapshot_v2)
    duplicate["label"] = "Do not overwrite v2"
    assert client.post(PATH, json=duplicate, headers=AUTH).json()["stored"] is False
    assert client.get(PATH + "/latest").json() == public_predictions._external_logos(snapshot_v2)


def test_v2_optional_fields_and_unavailable(client, snapshot_v2):
    del snapshot_v2["season"]
    del snapshot_v2["matchups"][0]["days"][0]["players"]
    snapshot_v2["teams"].append({"id": 4, "name": "Fourth", "abbrev": "F", "logo": None})
    snapshot_v2["matchups"].append({"home": 3, "away": 4, "unavailable": True})
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 200
    assert client.get(PATH + "/latest").json() == public_predictions._external_logos(snapshot_v2)


@pytest.mark.parametrize("manager", [None, "Jordan", "Anne-Marie O'Neil Jr.", "A" * 40])
@pytest.mark.parametrize("season", [2000, 2027, 2100])
def test_v2_accepts_season_year_and_public_manager(client, snapshot_v2, manager, season):
    snapshot_v2["season_year"] = season
    snapshot_v2["teams"][0]["manager"] = manager
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 200
    assert client.get(PATH + "/latest").json() == public_predictions._external_logos(snapshot_v2)


@pytest.mark.parametrize("manager", [
    "", " Jordan", "1Jordan", "Jordan42", "Jord@example.com", "Jord/Lee",
    "Mätthew", "Jord\nHo", "Jord\n", "A" * 41, 123, True,
])
def test_v2_rejects_private_or_invalid_manager(client, snapshot_v2, manager):
    snapshot_v2["teams"][0]["manager"] = manager
    response = client.post(PATH, json=snapshot_v2, headers=AUTH)
    assert response.status_code == 422
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("season", [1999, 2101, True, "2027", 2027.0])
def test_v2_rejects_invalid_season_year(client, snapshot_v2, season):
    snapshot_v2["season_year"] = season
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 422


def test_v2_season_is_still_a_forecast_object(client, snapshot_v2):
    snapshot_v2["season"] = 2027
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 422


@pytest.mark.parametrize("field", ["season", "season_year"])
def test_v1_still_rejects_season_and_manager(client, field):
    body = copy.deepcopy(SNAPSHOT)
    body[field] = 2027
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422
    del body[field]
    body["matchups"][0]["home"]["manager"] = "Jordan"
    assert client.post(PATH, json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize("path,key", [
    ([], "league_id"), (["teams", 0], "league_id"), (["matchup"], "private"),
    (["matchups", 0], "private"), (["matchups", 0, "days", 0], "private"),
    (["matchups", 0, "days", 0, "players", 0, 0], "slot"),
    (["matchups", 0, "days", 1, "players", 1, 0], "injury"),
    (["matchups", 0, "odds_history", 0], "private"), (["season"], "private"),
    (["season", "modes", "hot", 0], "private"),
    (["season", "history", "balanced", "1", 0], "private"),
    (["season", "modes"], "unknown"), (["season", "history"], "unknown"),
])
def test_v2_extra_fields_forbidden(client, snapshot_v2, path, key):
    target = snapshot_v2
    for part in path:
        target = target[part]
    target[key] = "private-value"
    response = client.post(PATH, json=snapshot_v2, headers=AUTH)
    assert response.status_code == 422
    assert "private-value" not in response.text
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("path,value", [
    (["teams"], []), (["teams", 1, "id"], 1), (["teams", 0, "id"], True),
    (["teams", 0, "name"], "x" * 61), (["teams", 0, "abbrev"], "x" * 13),
    (["teams", 0, "logo"], "https://other.example/logo.png"),
    (["teams", 0, "logo"], "https://g.espncdn.com.evil.example/logo.png"),
    (["teams", 0, "logo"], "http://g.espncdn.com/logo.png"),
    (["teams", 0, "logo"], "https://g.espncdn.com/" + "x" * 300),
    (["teams", 0, "logo"], "data:image/png;base64,bm90IGEgcG5n"),
    (["teams", 0, "logo"], "data:image/png;base64,%%%"),
    (["teams", 0, "logo"], "data:image/jpeg;base64,aGVsbG8="),
    (["teams", 0, "logo"], "data:image/png;base64," + base64.b64encode(
        PNG_SIGNATURE + b"x" * (MAX_LOGO_BYTES + 1 - len(PNG_SIGNATURE))).decode()),
    (["matchups", 0, "home"], 99), (["matchups", 0, "home"], "1"),
    (["matchups", 0, "away"], 1),
    (["matchups", 0, "days", 2, "players"], [[], []]),
    (["matchups", 0, "days", 0, "players"], [[]]),
    (["matchups", 0, "days", 0, "players"], [[], [], []]),
    (["matchups", 0, "days", 0, "players"], [[{"id": 1, "name": "P", "points": 0}] * 16, []]),
    (["matchups", 0, "days", 0, "players", 0, 0, "id"], -1),
    (["matchups", 0, "days", 0, "players", 0, 0, "id"], True),
    (["matchups", 0, "days", 0, "players", 0, 0, "name"], "x" * 61),
    (["matchups", 0, "days", 0, "players", 0, 0, "points"], "10"),
    (["season", "weeks_remaining"], -1), (["season", "weeks_remaining"], True),
    (["season", "playoff_teams"], 0), (["season", "playoff_teams"], 4),
    (["season", "trials"], 0), (["season", "trials"], 100001),
    (["season", "form_active"], 0),
    (["season", "modes"], {"unknown": []}),
    (["season", "modes", "hot", 0, "team"], 99),
    (["season", "modes", "hot", 0, "record"], [1, -1, 0]),
    (["season", "modes", "hot", 0, "record"], [1, 0]),
    (["season", "modes", "hot", 0, "record"], [True, 0, 0]),
    (["season", "modes", "hot", 0, "expected_wins"], -1),
    (["season", "modes", "hot", 0, "playoff_pct"], 101),
    (["season", "modes", "hot", 0, "title_pct"], -1),
    (["season", "modes", "hot", 0, "place_pct"], [40, 30, 20]),
    (["season", "modes", "hot", 0, "place_pct"], [100]),
    (["season", "modes", "hot", 0, "place_pct"], [101, 0, -1]),
    (["season", "history", "balanced"], {"99": []}),
    (["season", "history", "balanced"], {"01": []}),
    (["season", "history", "balanced", "1", 1, "date"], "2026-10-22"),
    (["season", "history", "balanced", "1", 1, "date"], "2026-10-21"),
    (["season", "history", "balanced", "1", 0, "playoff_pct"], 101),
    (["season", "history", "balanced", "1"], [{"date": "2026-10-22", "playoff_pct": 70}] * 61),
])
def test_v2_invalid_values(client, snapshot_v2, path, value):
    target = snapshot_v2
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 422
    assert not client.app.state.supabase.rows


@pytest.mark.parametrize("home,away", [(99, 3), (3, 99), (1, 3), (3, 3)])
def test_v2_unavailable_rejects_unknown_or_duplicate_teams(client, snapshot_v2, home, away):
    snapshot_v2["matchups"].append({"home": home, "away": away, "unavailable": True})
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
@pytest.mark.parametrize("path", [
    ["matchups", 0, "days", 0, "players", 0, 0, "points"],
    ["season", "modes", "hot", 0, "expected_wins"],
    ["season", "modes", "hot", 0, "place_pct", 0],
    ["season", "history", "balanced", "1", 0, "playoff_pct"],
])
def test_v2_strict_finite_numbers(client, snapshot_v2, path, value):
    target = snapshot_v2
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    assert client.post(PATH, content=json.dumps(snapshot_v2), headers=AUTH).status_code == 422


@pytest.mark.parametrize("total", [99.5, 100.5])
def test_v2_logo_size_and_probability_boundaries(client, snapshot_v2, total):
    snapshot_v2["teams"][0]["logo"] = "data:image/png;base64," + base64.b64encode(
        PNG_SIGNATURE + b"x" * (MAX_LOGO_BYTES - len(PNG_SIGNATURE))).decode()
    snapshot_v2["season"]["modes"]["hot"][0]["place_pct"] = [50, 30, total - 80]
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 200


@pytest.mark.parametrize("acquired", [
    {"how": "draft", "round": 11, "pick": 130}, {"how": "add"}, {"how": "trade"}, None,
])
def test_v2_accepts_how_a_player_was_acquired(client, snapshot_v2, acquired):
    snapshot_v2["matchups"][0]["days"][0]["players"][0][0]["acquired"] = acquired
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 200
    assert client.get(PATH + "/latest").json() == public_predictions._external_logos(snapshot_v2)


@pytest.mark.parametrize("acquired", [
    {"how": "draft"}, {"how": "draft", "round": 0, "pick": 1}, {"how": "draft", "round": 1, "pick": 1.5},
    {"how": "add", "round": 1}, {"how": "keeper"}, {"how": "add", "team_id": 4}, "draft",
])
def test_v2_rejects_malformed_acquisition(client, snapshot_v2, acquired):
    snapshot_v2["matchups"][0]["days"][0]["players"][0][0]["acquired"] = acquired
    assert client.post(PATH, json=snapshot_v2, headers=AUTH).status_code == 422


def test_server_league_id_never_reaches_public_predictions(client, monkeypatch):
    monkeypatch.setenv("ESPN_FANTASY_LEAGUE_ID", "918273645")
    assert client.post(PATH, json=SNAPSHOT, headers=AUTH).status_code == 200
    response = client.get(PATH + "/latest")
    assert response.status_code == 200 and "918273645" not in response.text
    assert "leagueId" not in response.text and "league_id" not in response.text


def test_logos_are_outside_payload_and_cacheable(client, snapshot_v2):
    client.post(PATH, json=snapshot_v2, headers=AUTH)
    result = client.get(PATH + "/latest")
    path = result.json()["teams"][0]["logo"]
    assert path.startswith("/espn/public/logos/") and "data:image" not in result.text
    assert client.app.state.supabase.rows[0]["payload"]["teams"][0]["logo"] == PNG_LOGO
    image = client.get(path)
    assert image.content == base64.b64decode(PNG_LOGO.split(",")[1])
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get(path, headers={"If-None-Match": image.headers["etag"]}).status_code == 304
    public_predictions._logos.clear()  # a different worker can rebuild from the public snapshot
    assert client.get(path).content == image.content
    assert client.get("/espn/public/logos/" + "0" * 64).status_code == 404
    assert client.get("/espn/public/logos/invalid").status_code == 404
    cached = client.get(PATH + "/latest", headers={"If-None-Match": result.headers["etag"]})
    assert cached.status_code == 304 and not cached.content


def test_empty_database_uses_existing_validated_public_fallback(client, snapshot_v2, monkeypatch):
    monkeypatch.setattr(team_claims, "_fallback_snapshot", lambda: snapshot_v2)
    response = client.get(PATH + "/latest")
    assert response.status_code == 200
    assert response.json() == public_predictions._external_logos(snapshot_v2)
