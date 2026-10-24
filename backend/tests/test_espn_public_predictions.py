"""Public uploads/reads with an in-memory Supabase boundary; no ESPN calls."""

import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import routes
from espn.public_predictions import MAX_BODY_BYTES

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
    (["matchups"], SNAPSHOT["matchups"] * 21),
    (["matchups", 0, "days"], SNAPSHOT["matchups"][0]["days"] * 15),
    (["matchups", 0, "odds_history"], SNAPSHOT["matchups"][0]["odds_history"] * 31),
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


def test_body_limit_accepts_exactly_256_kib(client):
    content = json.dumps(SNAPSHOT).encode()
    content += b" " * (MAX_BODY_BYTES - len(content))
    assert client.post(PATH, content=content, headers=AUTH).status_code == 200
