"""Claims HTTP flow with fake Supabase Auth, profile storage, and atomic RPCs."""

from copy import deepcopy
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from espn import routes
from espn import team_claims
from espn.team_claims import _similarity

REAL_FALLBACK = team_claims._fallback_snapshot

AUTH = {"Authorization": "Bearer owner"}
SNAPSHOT = {
    "version": "public-v2", "season_year": 2027,
    "captured_at": "2026-10-23T11:00:00Z",
    "teams": [
        {"id": 1, "name": "Home", "manager": "Matthew"},
        {"id": 2, "name": "Away", "manager": "Jason"},
        {"id": 3, "name": "Matt's All Stars", "manager": None},
        {"id": 4, "name": "Fourth", "manager": "Taylor"},
    ],
}


def duplicate():
    return APIError({"code": "23505", "message": "duplicate key", "details": None, "hint": None})


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.columns = None
        self.ordering = None
        self.count = None
        self.deleting = False

    def select(self, columns):
        self.columns = columns.split(",")
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row[key] == value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row[key] in values)
        return self

    def or_(self, expression):
        match = re.fullmatch(
            r"payload->>season_year.eq.(\d+),and\(payload->>season_year.is.null,"
            r"payload->>captured_at.gte.(\d{4}-07-01),payload->>captured_at.lt.(\d{4}-07-01)\)",
            expression,
        )
        assert match, expression
        year, start, end = match.groups()
        self.filters.append(lambda row: (
            row["payload"].get("season_year") == int(year)
            or (row["payload"].get("season_year") is None
                and start <= row["payload"]["captured_at"] < end)
        ))
        return self

    def order(self, key, desc=False):
        self.ordering = (key, desc)
        return self

    def limit(self, count):
        self.count = count
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        rows = [row for row in self.db.tables[self.table]
                if all(predicate(row) for predicate in self.filters)]
        if self.deleting:
            self.db.tables[self.table][:] = [row for row in self.db.tables[self.table] if row not in rows]
        if self.ordering:
            key, desc = self.ordering
            rows.sort(key=lambda row: row[key], reverse=desc)
        if self.count is not None:
            rows = rows[:self.count]
        if self.columns is not None:
            rows = [{key: row[key] for key in self.columns} for row in rows]
        return SimpleNamespace(data=deepcopy(rows))


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "espn_public_predictions": [{"received_at": "2026-10-23", "payload": deepcopy(SNAPSHOT)}],
            "espn_team_claims": [],
            "dice_profiles": [{"user_id": "owner-id", "display_name": "Matt", "avatar_url": None}],
        }
        self.users = {
            "owner": ("owner-id", "owner@example.test", {"full_name": "Matthew Ho"}),
            "other": ("other-id", "other@example.test", {}),
            "admin": ("admin-id", "homatt999@gmail.com", {}),
            "jason-admin": ("jason-id", "jason.keungg@gmail.com", {}),
        }
        self.auth = SimpleNamespace(get_user=self.get_user)
        self.rpc_calls = []
        self.race_team = None

    def get_user(self, token):
        user_id, email, metadata = self.users[token]
        return SimpleNamespace(user=SimpleNamespace(id=user_id, email=email, user_metadata=metadata))

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, args):
        assert name == "espn_claim_team"
        self.rpc_calls.append((name, args))

        def execute():
            claims = self.tables["espn_team_claims"]
            season, team_id, user_id = (args[key] for key in ("p_season", "p_team_id", "p_user_id"))
            if self.race_team == team_id:
                self.add_claim(team_id, "racing-user", season)
            before = deepcopy(claims)
            try:
                if any(row["season"] == season and row["team_id"] == team_id
                       and row["user_id"] == user_id for row in claims):
                    return SimpleNamespace(data=None)
                claims[:] = [row for row in claims
                             if (row["season"], row["user_id"]) != (season, user_id)]
                if any(row["season"] == season and row["team_id"] == team_id for row in claims):
                    raise duplicate()
                self.add_claim(team_id, user_id, season)
            except APIError:
                claims[:] = before
                raise
            return SimpleNamespace(data=None)

        return SimpleNamespace(execute=execute)

    def add_claim(self, team_id, user_id="owner-id", season=2027):
        self.tables["espn_team_claims"].append({
            "id": f"claim-{season}-{team_id}-{user_id}", "season": season,
            "team_id": team_id, "user_id": user_id,
        })


@pytest.fixture(autouse=True)
def no_fallback(monkeypatch):
    # Tests never reach the interim snapshot host unless they opt in.
    monkeypatch.setattr(team_claims, "_fallback_snapshot", lambda: None)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/espn")
    app.state.supabase = FakeSupabase()
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path,body", [
    ("get", "/espn/claims/suggestions", None),
    ("post", "/espn/claims", {"season": 2027, "team_id": 1}),
    ("delete", "/espn/claims/2027/1", None),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_claim_routes_require_cozy_auth(client, method, path, body, headers):
    response = client.request(method, path, json=body, headers=headers)
    assert response.status_code in (401, 403)
    assert not client.app.state.supabase.rpc_calls


@pytest.mark.parametrize("display_name,metadata", [
    ("Matthew Ho", {}), ("Matt", {}),
    ("Player", {"full_name": "Matthew Ho"}), ("Player", {"name": "Matthew Ho"}),
    ("Player", {"given_name": "Matthew"}),
])
def test_suggestions_rank_names_and_only_expose_public_fields(client, display_name, metadata):
    db = client.app.state.supabase
    db.tables["dice_profiles"][0]["display_name"] = display_name
    db.users["owner"] = ("owner-id", "owner@example.test", metadata)
    db.add_claim(1)
    db.add_claim(2, "other-id")
    response = client.get("/espn/claims/suggestions", headers=AUTH)
    body = response.json()
    assert body["season"] == 2027 and body["has_profile"] is True
    assert body["mine"] == {"team_id": 1}
    assert body["teams"][0]["team_id"] == 1
    assert body["teams"][0]["score"] > body["teams"][1]["score"]
    assert body["teams"][0]["claimed"] is True and body["teams"][0]["mine"] is True
    other = next(team for team in body["teams"] if team["team_id"] == 2)
    assert other["claimed"] is True and other["mine"] is False
    for team in body["teams"]:
        assert 0 <= team["score"] <= 1
        assert set(team) == {"team_id", "name", "manager", "score", "claimed", "mine", "can_claim"}
    for secret in ("owner-id", "other-id", "@", "user_id", "email"):
        assert secret not in response.text


def test_normalized_token_matching_and_first_name_weight():
    assert _similarity("MÁTThew Ho", "Matthew") >= 0.95
    assert _similarity("Ho, Matthew", "Matthew Ho") == 1
    assert _similarity("Anne-Marie O'Neil", "anne marie oneil") > 0.8
    assert _similarity("Matt", "Matthew") > _similarity("Matt", "Jason")
    assert _similarity("", "Matthew") == 0


def test_suggestions_without_profile_or_snapshot(client):
    db = client.app.state.supabase
    db.tables["dice_profiles"].clear()
    body = client.get("/espn/claims/suggestions", headers=AUTH).json()
    assert body["has_profile"] is False and body["teams"][0]["team_id"] == 1
    assert body["mine"] is None
    db.tables["espn_public_predictions"].clear()
    assert client.get("/espn/claims/suggestions", headers=AUTH).json() == {
        "season": None, "has_profile": False, "mine": None, "teams": [],
    }


def share_manager(db, team_id, name="Matthew"):
    for team in db.tables["espn_public_predictions"][0]["payload"]["teams"]:
        if team["id"] == team_id:
            team["manager"] = name


def test_claim_confirm_retry_and_move(client):
    db = client.app.state.supabase
    share_manager(db, 2)
    for team_id in (1, 1, 2):
        response = client.post("/espn/claims", json={"season": 2027, "team_id": team_id}, headers=AUTH)
        assert response.status_code == 200
        assert response.json() == {"season": 2027, "team_id": team_id}
        assert [(row["team_id"], row["user_id"]) for row in db.tables["espn_team_claims"]] == [
            (team_id, "owner-id"),
        ]
        assert db.rpc_calls[-1] == ("espn_claim_team", {
            "p_season": 2027, "p_team_id": team_id, "p_user_id": "owner-id",
        })


def test_claim_requires_a_name_match_unless_admin(client):
    db = client.app.state.supabase
    body = client.get("/espn/claims/suggestions", headers=AUTH).json()
    assert {t["team_id"]: t["can_claim"] for t in body["teams"]}[2] is False
    response = client.post("/espn/claims", json={"season": 2027, "team_id": 2}, headers=AUTH)
    assert response.status_code == 403 and response.json()["detail"] == "name_mismatch"
    assert not db.rpc_calls
    db.tables["dice_profiles"].append({"user_id": "admin-id", "display_name": "Zed", "avatar_url": None})
    admin = {"Authorization": "Bearer admin"}
    teams = client.get("/espn/claims/suggestions", headers=admin).json()["teams"]
    assert all(team["can_claim"] for team in teams)
    assert client.post("/espn/claims", json={"season": 2027, "team_id": 2}, headers=admin).status_code == 200


def test_claim_requires_profile(client):
    client.app.state.supabase.tables["dice_profiles"].clear()
    response = client.post("/espn/claims", json={"season": 2027, "team_id": 1}, headers=AUTH)
    assert response.status_code == 409 and response.json()["detail"] == "profile_required"
    assert not client.app.state.supabase.rpc_calls


@pytest.mark.parametrize("racing", [False, True])
def test_conflicting_claim_preserves_previous_team(client, racing):
    db = client.app.state.supabase
    share_manager(db, 2)
    db.add_claim(1)
    if racing:
        db.race_team = 2
    else:
        db.add_claim(2, "other-id")
    response = client.post("/espn/claims", json={"season": 2027, "team_id": 2}, headers=AUTH)
    assert response.status_code == 409 and response.json()["detail"] == "team_claimed"
    assert any(row["user_id"] == "owner-id" and row["team_id"] == 1
               for row in db.tables["espn_team_claims"])


@pytest.mark.parametrize("season,team_id", [(2027, 99), (2026, 1)])
def test_claim_unknown_team_or_season(client, season, team_id):
    response = client.post("/espn/claims", json={"season": season, "team_id": team_id}, headers=AUTH)
    assert response.status_code == 404
    assert not client.app.state.supabase.rpc_calls


@pytest.mark.parametrize("body", [
    {"season": True, "team_id": 1}, {"season": 1999, "team_id": 1},
    {"season": 2101, "team_id": 1}, {"season": "2027", "team_id": 1},
    {"season": 2027, "team_id": True}, {"season": 2027, "team_id": 1, "user_id": "other-id"},
])
def test_claim_body_validation(client, body):
    assert client.post("/espn/claims", json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize("token", ["owner", "admin", "jason-admin", "other"])
def test_delete_permissions(client, token):
    db = client.app.state.supabase
    db.add_claim(1)
    response = client.delete("/espn/claims/2027/1", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == (403 if token == "other" else 200)
    assert bool(db.tables["espn_team_claims"]) == (token == "other")


def test_delete_unknown_claim(client):
    assert client.delete("/espn/claims/2027/1", headers=AUTH).status_code == 404


@pytest.mark.parametrize("avatar,expected", [
    ("https://images.example.test/avatar.png", "https://images.example.test/avatar.png"),
    ("http://images.example.test/avatar.png", None), ("javascript:alert(1)", None),
    ("https://", None), ("data:image/png;base64,abc", None), (None, None),
])
def test_public_list_joins_profiles_and_limits_output(client, avatar, expected):
    db = client.app.state.supabase
    db.tables["dice_profiles"][0]["avatar_url"] = avatar
    db.add_claim(1)
    db.add_claim(2, "deleted-profile-id")
    response = client.get("/espn/public/claims?season=2027")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.json() == [{"team_id": 1, "display_name": "Matt", "avatar_url": expected}]
    for secret in ("user_id", "email", "owner-id", "deleted-profile-id", "@"):
        assert secret not in response.text


@pytest.mark.parametrize("query", ["", "?season=1999", "?season=2099"])
def test_public_unknown_or_absent_season_uses_latest(client, query):
    client.app.state.supabase.add_claim(1)
    assert client.get("/espn/public/claims" + query).json()[0]["team_id"] == 1


def test_public_empty_before_snapshot_is_cached(client):
    client.app.state.supabase.tables["espn_public_predictions"].clear()
    response = client.get("/espn/public/claims")
    assert response.json() == [] and response.headers["cache-control"] == "public, max-age=60"


def test_explicit_season_year_overrides_captured_at(client):
    db = client.app.state.supabase
    db.tables["espn_public_predictions"][0]["payload"]["season_year"] = 2030
    assert client.get("/espn/claims/suggestions", headers=AUTH).json()["season"] == 2030
    assert client.post("/espn/claims", json={"season": 2030, "team_id": 1}, headers=AUTH).status_code == 200
    assert db.tables["espn_team_claims"][0]["season"] == 2030
    assert client.get("/espn/public/claims?season=2030").json()[0]["team_id"] == 1


def test_latest_snapshot_within_requested_season_and_isolated_claims(client):
    db = client.app.state.supabase
    old = deepcopy(SNAPSHOT)
    old.update(season_year=2026, captured_at="2025-10-23T11:00:00Z")
    old["teams"] = [{"id": 8, "name": "Old team", "manager": "Matthew"}]
    newest = deepcopy(old)
    newest["teams"] = [{"id": 9, "name": "Renamed team", "manager": "Matthew"}]
    db.tables["espn_public_predictions"].extend([
        {"received_at": "2025-10-23", "payload": old},
        {"received_at": "2025-10-24", "payload": newest},
    ])
    db.add_claim(1)
    assert client.post("/espn/claims", json={"season": 2026, "team_id": 8}, headers=AUTH).status_code == 404
    assert client.get("/espn/public/claims?season=2026").json() == []
    assert client.post("/espn/claims", json={"season": 2026, "team_id": 9}, headers=AUTH).status_code == 200
    assert {row["season"] for row in db.tables["espn_team_claims"]} == {2026, 2027}
    assert client.get("/espn/public/claims?season=2026").json()[0]["team_id"] == 9
    assert client.get("/espn/claims/suggestions", headers=AUTH).json()["mine"] == {"team_id": 1}


@pytest.mark.parametrize("captured,year", [
    ("2026-06-30T23:59:59Z", 2026), ("2026-07-01T00:00:00Z", 2027),
])
def test_legacy_snapshot_year_rollover(client, captured, year):
    db = client.app.state.supabase
    payload = db.tables["espn_public_predictions"][0]["payload"]
    del payload["season_year"]
    payload["captured_at"] = captured
    payload["season"] = {"modes": {}}  # Forecast data is never interpreted as a year.
    assert client.get("/espn/claims/suggestions", headers=AUTH).json()["season"] == year
    assert client.post("/espn/claims", json={"season": year, "team_id": 1}, headers=AUTH).status_code == 200
    assert client.get(f"/espn/public/claims?season={year}").json()[0]["team_id"] == 1
    db.tables["espn_public_predictions"].append({"received_at": "2028-01-01", "payload": SNAPSHOT})
    assert client.get(f"/espn/public/claims?season={year}").json()[0]["team_id"] == 1


def test_claims_use_the_interim_snapshot_until_uploads_exist(client, monkeypatch):
    db = client.app.state.supabase
    db.tables["espn_public_predictions"].clear()
    monkeypatch.setattr(team_claims, "_fallback_snapshot", lambda: deepcopy(SNAPSHOT))
    body = client.get("/espn/claims/suggestions", headers=AUTH).json()
    assert body["season"] == 2027 and body["teams"][0]["team_id"] == 1
    assert client.post("/espn/claims", json={"season": 2027, "team_id": 1}, headers=AUTH).status_code == 200
    assert client.post("/espn/claims", json={"season": 2026, "team_id": 1}, headers=AUTH).status_code == 404


def test_fallback_fetch_validates_caches_and_fails_closed(monkeypatch):
    import json
    calls = []

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return self.body

    def urlopen(url, timeout):  # Stands in for the redirect-refusing opener.
        calls.append(url)
        return Response(body)

    monkeypatch.setattr(team_claims, "_fallback_snapshot", REAL_FALLBACK)
    monkeypatch.setattr(team_claims._NO_REDIRECTS, "open", urlopen)
    monkeypatch.setitem(team_claims._fallback_cache, "at", 0.0)
    body = json.dumps({"version": "public-v2", "generated_at": "2026-10-23T12:00:00Z", "captured_at": "2026-10-23T11:00:00Z",
                       "label": "x", "matchup": {"id": 1, "ends": "2026-10-25"},
                       "teams": [{"id": 1, "name": "Home", "abbrev": "H", "logo": None}, {"id": 2, "name": "Away", "abbrev": "A", "logo": None}], "matchups": []}).encode()
    first = team_claims._fallback_snapshot()
    assert first["teams"][0]["id"] == 1
    assert team_claims._fallback_snapshot() is first and len(calls) == 1
    monkeypatch.setitem(team_claims._fallback_cache, "at", 0.0)
    body = b'{"version": "public-v2", "player_name": "x"}'
    assert team_claims._fallback_snapshot() is None
