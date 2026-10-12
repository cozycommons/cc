"""HTTP-level tests for the ESPN Fantasy FastAPI routes.

FastAPI TestClient with every external boundary faked: account resolution,
the ESPN wire client, snapshot storage, and onboarding. Covers auth, error
mapping, the snapshot-based trends endpoint, and that /matchups does not
exist in v1.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import routes
from espn.accounts import AccountError

FAKE_ACCOUNT = {
    "id": "acc-1",
    "label": "warner",
    "league_id": 123456,
    "season": 2027,
    "espn_s2": "s2-secret",
    "swid": "{SWID-1}",
}

LEAGUE_PAYLOAD = {
    "id": 123456,
    "seasonId": 2027,
    "settings": {"name": "Fantasy Hoops '27", "size": 2,
                 "scoringSettings": {"scoringItems": []}},
    "status": {"currentMatchupPeriod": 1, "currentScoringPeriod": 10,
               "firstScoringPeriod": 1},
    "members": [
        {"id": "m1", "displayName": "Alice"},
        {"id": "m2", "displayName": "Bob"},
    ],
    "teams": [
        {
            "id": 1, "abbrev": "ALP", "name": "Alpha", "owners": ["m1"],
            "record": {"overall": {
                "wins": 3, "losses": 1, "ties": 0,
                "pointsFor": 400.0, "pointsAgainst": 350.0,
                "streak": {"type": "WIN", "length": 1},
            }},
            "roster": {"entries": []},
        },
        {
            "id": 2, "abbrev": "BET", "name": "Beta", "owners": ["m2"],
            "record": {"overall": {
                "wins": 1, "losses": 3, "ties": 0,
                "pointsFor": 300.0, "pointsAgainst": 380.0,
                "streak": {"type": "LOSS", "length": 2},
            }},
            "roster": {"entries": []},
        },
    ],
    "schedule": [],
    "transactions": [],
    "draftDetail": {"drafted": False, "picks": []},
}


class FakeClient:
    """Minimal ESPN wire fake for route tests (no network)."""

    league_id = 123456
    season = 2027

    def get_league(self, views):
        return LEAGUE_PAYLOAD

    def get_players(self, limit=300):
        return []


CURRENT_SNAP = {
    "league_id": 123456,
    "season": 2027,
    "name": "Fantasy Hoops '27",
    "current_scoring_period": 10,
    "current_matchup_period": 1,
    "teams": [],
    "players": [
        {"player_id": 1, "name": "Hot", "team_id": 1,
         "percent_owned": 80.0, "percent_started": 70.0,
         "percent_change": 3.5, "season_fantasy_points": 100.0,
         "recent7_fantasy_points": 105.0},
        {"player_id": 2, "name": "Cold", "team_id": 2,
         "percent_owned": 40.0, "percent_started": 30.0,
         "percent_change": -2.0, "season_fantasy_points": 200.0,
         "recent7_fantasy_points": 70.0},
    ],
}


@pytest.fixture()
def app(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router, prefix="/espn")
    application.state.supabase = object()  # never touched; boundaries faked

    def fake_get_account(supabase, token):
        if token == "good-token":
            return dict(FAKE_ACCOUNT)
        raise AccountError("invalid token")

    def fake_make_client(account):
        return FakeClient()

    def fake_ensure_snapshot(supabase, account, client, max_age_s=3600):
        return {
            "current": CURRENT_SNAP,
            "previous": None,
            "captured_at": "2026-10-12T00:00:00Z",
            "fresh_capture": True,
        }

    def fake_latest_snapshots(supabase, account_id, limit=2):
        return [{"captured_at": "2026-10-12T00:00:00Z"}]

    monkeypatch.setattr(routes.accounts, "get_account_by_token", fake_get_account)
    monkeypatch.setattr(routes.accounts, "make_client_for_account", fake_make_client)
    monkeypatch.setattr(routes.snapshots, "ensure_snapshot", fake_ensure_snapshot)
    monkeypatch.setattr(routes.snapshots, "latest_snapshots", fake_latest_snapshots)
    routes._ONBOARD_ATTEMPTS.clear()
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


def auth(token="good-token"):
    return {"Authorization": f"Bearer {token}"}


# --- auth --------------------------------------------------------------------


def test_no_token_is_401(client):
    r = client.get("/espn/me")
    assert r.status_code == 401


def test_bad_token_is_401(client):
    r = client.get("/espn/me", headers=auth("bogus-token"))
    assert r.status_code == 401


def test_me_shape(client):
    r = client.get("/espn/me", headers=auth())
    assert r.status_code == 200
    assert r.json() == {
        "id": "acc-1",
        "label": "warner",
        "league_id": 123456,
        "season": 2027,
    }


# --- reads ---------------------------------------------------------------------


def test_standings(client):
    r = client.get("/espn/standings", headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert [s["team_id"] for s in body["standings"]] == [1, 2]
    assert body["standings"][0]["rank"] == 1


def test_league(client):
    r = client.get("/espn/league", headers=auth())
    assert r.status_code == 200
    assert r.json()["name"] == "Fantasy Hoops '27"


def test_team_detail(client):
    r = client.get("/espn/teams/1", headers=auth())
    assert r.status_code == 200
    assert r.json()["team"]["name"] == "Alpha"


def test_unknown_team_is_404(client):
    r = client.get("/espn/teams/99", headers=auth())
    assert r.status_code == 404


def test_player_trends_snapshot_shape(client):
    r = client.get("/espn/trends/players", headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ownership", "performance", "snapshot"}
    # first snapshot (previous=None): ESPN's own fallbacks are the source
    assert body["ownership"]["source"] == "espn_percent_change"
    assert [p["player_id"] for p in body["ownership"]["most_added"]] == [1]
    assert body["performance"]["source"] == "espn_splits"
    assert [p["player_id"] for p in body["performance"]["risers"]] == [1]
    assert body["snapshot"] == {
        "captured_at": "2026-10-12T00:00:00Z",
        "fresh_capture": True,
        "history": False,
    }


def test_matchups_route_does_not_exist(client):
    r = client.get("/espn/matchups", headers=auth())
    assert r.status_code == 404


# --- onboarding ------------------------------------------------------------------


def test_onboard_returns_token_once(client, monkeypatch):
    def fake_create(supabase, label, league_id, season, espn_s2, swid):
        assert league_id == 123456
        assert season == 2027
        assert espn_s2 == "s2-secret"
        assert swid == "{SWID-1}"
        return {
            "id": "acc-9",
            "label": label,
            "league_id": league_id,
            "season": season,
            "token": "cce_secret_once",
        }

    monkeypatch.setattr(routes.accounts, "create_account", fake_create)
    r = client.post("/espn/onboard", json={
        "label": "espn",
        "league_id": 123456,
        "season": 2027,
        "espn_s2": "s2-secret",
        "swid": "{SWID-1}",
    })
    assert r.status_code == 200
    assert r.json()["token"] == "cce_secret_once"
    assert r.json()["id"] == "acc-9"
