"""Name and avatar have one writer, commons_profiles; Dice, Trips, ESPN and whoami read it (M4 PR 2)."""
from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dice.routes import router as dice_router
from espn import routes as espn_routes, team_claims
from runtime_policy import initialize_runtime_policy
from tests.test_dice import (ADMIN_TOKEN, AUTH_USERS, HOST_TOKEN, OTHER_TOKEN, ROSTER, _FakeAuth, _FakeSupabase,
                             _anonymous_roster, _headers, _log_game, _seed)
from trips.ledger import new_group
from trips.profiles import render_groups, stored_profile

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = {"version": "public-v2", "season_year": 2027, "captured_at": "2026-10-23T11:00:00Z",
            "teams": [{"id": 1, "name": "Home", "manager": "Andrew"}]}


class MirroredSupabase(_FakeSupabase):
    """The Dice fake plus 0087's trigger: a commons_profiles name or avatar update is copied into dice_profiles."""

    def __init__(self):
        super().__init__()
        self.dice_writes = []

    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def run():
            if name == "dice_profiles" and query._op in ("insert", "update", "upsert"):
                self.dice_writes.append(dict(query._payload))
            result = execute()
            if name == "commons_profiles" and query._op == "update":
                mirrored = {key: query._payload[key] for key in ("display_name", "avatar_url") if key in query._payload}
                for row in result.data:
                    for dice in self.tables.get("dice_profiles", []):
                        if dice["user_id"] == row["user_id"]:
                            dice.update(mirrored)
            return result

        query.execute = run
        return query


def commons_row(profile):
    return {"user_id": profile["user_id"], "display_name": profile["display_name"], "avatar_url": profile["avatar_url"],
            "venmo_username": None, "venmo_owner_confirmed": False, "venmo_confirmed_name": None}


@pytest.fixture
def commons(monkeypatch):
    monkeypatch.setattr(team_claims, "_fallback_snapshot", lambda: None)

    def build(profiles=None):
        profiles = deepcopy(profiles or ROSTER)
        db = MirroredSupabase()
        db.auth = _FakeAuth(deepcopy(AUTH_USERS))
        db.tables.update({
            "dice_profiles": profiles,
            # 0087/0088 backfill: every existing account has a Commons row.
            "commons_profiles": [commons_row(profile) for profile in profiles],
            "espn_public_predictions": [{"received_at": "2026-10-23", "payload": deepcopy(SNAPSHOT)}],
            "espn_team_claims": [{"id": "c1", "season": 2027, "team_id": 1, "user_id": "u1"}],
        })
        app = FastAPI()
        app.include_router(dice_router, prefix="/dice")
        app.include_router(espn_routes.router, prefix="/espn")
        app.state.runtime_policy = initialize_runtime_policy({"DICE_LOCAL_HARNESS": "true"}, lambda: None)
        app.state.supabase = app.state.supabase_admin = db
        return TestClient(app), db

    return build


def seen_everywhere(client, db, user_id):
    """The name and avatar each non-Dice reader shows for one user."""
    row = new_group(str(uuid4()), user_id, "Trip", "USD", "Source name")
    trips = render_groups(db, [row])[0]["members"][0]
    claims = client.get("/espn/public/claims").json()
    claim = next(c for c in claims if c["team_id"] == 1)
    whoami = stored_profile(db, SimpleNamespace(id=user_id, user_metadata={}))
    return {"trips": (trips["display_name"], trips["avatar_url"]),
            "espn": (claim["display_name"], claim["avatar_url"]),
            "whoami": whoami["display_name"]}


def test_dice_name_and_avatar_edit_reaches_trips_espn_and_whoami(commons):
    client, db = commons()
    avatar = "https://images.example.test/andrew.png"
    response = client.put("/dice/me", headers=_headers(HOST_TOKEN), json={"display_name": "Andrew Edited", "avatar_url": avatar})
    assert response.status_code == 200, response.text
    assert (response.json()["display_name"], response.json()["avatar_url"]) == ("Andrew Edited", avatar)
    assert seen_everywhere(client, db, "u1") == {
        "trips": ("Andrew Edited", avatar), "espn": ("Andrew Edited", avatar), "whoami": "Andrew Edited"}
    assert client.get("/dice/profiles/u1").json()["display_name"] == "Andrew Edited"
    suggestions = client.get("/espn/claims/suggestions", headers=_headers(HOST_TOKEN)).json()
    assert suggestions["has_profile"] is True and suggestions["teams"][0]["can_claim"] is True


def test_admin_rename_is_commons_wide(commons):
    client, db = commons()
    response = client.put("/dice/me", headers=_headers(ADMIN_TOKEN), json={"user_id": "u1", "display_name": "Renamed By Admin"})
    assert response.status_code == 200, response.text
    assert seen_everywhere(client, db, "u1")["trips"][0] == "Renamed By Admin"
    member = client.put("/dice/me", headers=_headers(OTHER_TOKEN), json={"user_id": "u1", "display_name": "Nope"})
    assert member.status_code == 403
    assert seen_everywhere(client, db, "u1")["whoami"] == "Renamed By Admin"


def test_only_commons_profiles_writes_name_and_avatar(commons):
    client, db = commons(profiles=[p for p in ROSTER if p["user_id"] != "u4"])
    # A new Dice player: the row is created once, from the Commons profile.
    created = client.get("/dice/me", headers=_headers(OTHER_TOKEN)).json()
    commons_jaycee = next(row for row in db.tables["commons_profiles"] if row["user_id"] == "u4")
    assert db.dice_writes == [{**db.dice_writes[0], "display_name": commons_jaycee["display_name"],
                               "avatar_url": commons_jaycee["avatar_url"]}]
    assert created["display_name"] == commons_jaycee["display_name"]
    db.dice_writes.clear()
    for token, body in [
        (HOST_TOKEN, {"display_name": "New Name", "avatar_url": "https://images.example.test/n.png",
                      "phone_number": "+14155551234", "is_anonymous": False}),
        (ADMIN_TOKEN, {"user_id": "u1", "display_name": "Admin Name"}),
        (HOST_TOKEN, {"avatar_url": ""}),
    ]:
        assert client.put("/dice/me", headers=_headers(token), json=body).status_code == 200
    assert client.get("/dice/me", headers=_headers(HOST_TOKEN)).status_code == 200
    assert db.dice_writes and all({"display_name", "avatar_url"}.isdisjoint(write) for write in db.dice_writes)
    andrew = next(row for row in db.tables["commons_profiles"] if row["user_id"] == "u1")
    assert (andrew["display_name"], andrew["avatar_url"]) == ("Admin Name", "")


def test_no_other_python_code_writes_dice_names_or_avatars():
    # Every Python write to dice_profiles goes through dice.repository. Name and avatar
    # reach that table only through the 0087 mirror (and the creation insert above).
    writers = set()
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        for line in path.read_text().splitlines():
            if re.search(r"(dice_profiles|PROFILES_TABLE)\W*\)\s*\.(update|upsert|insert)\(", line):
                writers.add(str(path.relative_to(BACKEND)))
    assert writers == {"dice/repository.py"}


def test_blank_name_and_oversized_avatar_are_rejected_before_any_write(commons):
    client, db = commons()
    before = deepcopy(db.tables)
    assert client.put("/dice/me", headers=_headers(HOST_TOKEN), json={"display_name": "   "}).status_code == 400
    too_long = "https://images.example.test/" + "a" * 2048
    assert client.put("/dice/me", headers=_headers(HOST_TOKEN), json={"avatar_url": too_long}).status_code == 400
    assert db.tables == before


def test_missing_dice_profile_is_still_404_and_writes_nothing(commons):
    client, db = commons(profiles=[p for p in ROSTER if p["user_id"] != "u4"])
    before = deepcopy(db.tables)
    response = client.put("/dice/me", headers=_headers(OTHER_TOKEN), json={"display_name": "Ghost"})
    assert response.status_code == 404
    assert db.tables == before


def test_anonymous_player_stays_aliased_after_an_avatar_change(commons):
    client, db = commons(profiles=_anonymous_roster("u1"))
    avatar = "https://images.example.test/secret.png"
    assert client.put("/dice/me", headers=_headers(HOST_TOKEN), json={"avatar_url": avatar}).status_code == 200
    assert next(p for p in db.tables["dice_profiles"] if p["user_id"] == "u1")["avatar_url"] == avatar
    _log_game(client)
    games = client.get("/dice/games?limit=10", headers={**_headers(OTHER_TOKEN), **_seed()}).json()
    anonymous = next(p for p in games[0]["players"] if p["user_id"].startswith("anon-"))
    assert anonymous["display_name"].startswith("Anonymous ") and anonymous["avatar_url"] is None
    assert avatar not in str(games) and "u1" not in str(games)


def test_trips_venmo_save_writes_commons_profiles_not_auth_metadata(commons, monkeypatch):
    from trips.routes import router as trips_router
    from venmo.profiles import lookup

    client, db = commons()
    metadata_writes = []
    db.auth.admin = SimpleNamespace(update_user_by_id=lambda *args: metadata_writes.append(args))
    monkeypatch.setattr(lookup, "load", lambda _client, handle: {"found": True, "displayName": "Andrew S"})
    client.app.include_router(trips_router, prefix="/trips")
    client.app.state.trips_supabase = db
    saved = client.put("/trips/me", headers=_headers(HOST_TOKEN), json={"venmo_username": "@Andrew-Pays", "owner_confirmed": True})
    assert saved.status_code == 200, saved.text
    assert {key: saved.json()[key] for key in ("display_name", "venmo_username", "venmo_confirmed", "venmo_confirmed_name")} == {
        "display_name": "Andrew S", "venmo_username": "andrew-pays", "venmo_confirmed": True, "venmo_confirmed_name": "Andrew S"}
    andrew = next(row for row in db.tables["commons_profiles"] if row["user_id"] == "u1")
    assert (andrew["venmo_username"], andrew["venmo_owner_confirmed"]) == ("andrew-pays", True)
    assert metadata_writes == [] and db.dice_writes == []
    cleared = client.put("/trips/me", headers=_headers(HOST_TOKEN), json={"venmo_username": ""}).json()
    assert (cleared["venmo_username"], cleared["venmo_confirmed"]) == (None, False) and "venmo_confirmed_name" not in cleared
