"""HTTP-level tests for the Maple telemetry FastAPI routes.

FastAPI TestClient with the real accounts/logic code over an in-memory
fake Supabase — covers onboarding, auth, ingest (including idempotent
re-posts), reads and per-account isolation.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maple import routes
from tests.maple_fakes import FakeSupabase
from tests.test_maple_logic import ENTRY


@pytest.fixture()
def db():
    return FakeSupabase()


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.state.maple_supabase = db
    app.include_router(routes.router, prefix="/telemetry")
    routes._ONBOARD_ATTEMPTS.clear()
    return TestClient(app)


def onboard(client, label="warner"):
    r = client.post("/telemetry/onboard", json={"label": label})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_onboard_mints_token_once(client, db):
    created = onboard(client)
    assert created["token"].startswith("ccm_")
    assert created["label"] == "warner"
    stored = db.stores["maple_accounts"][0]
    assert created["token"] not in str(stored)


def test_no_token_is_401(client):
    assert client.get("/telemetry/me").status_code == 401
    assert client.get("/telemetry/exp/runs").status_code == 401
    assert client.post("/telemetry/ingest/exp-runs", json={"runs": []}).status_code == 401


def test_bad_token_is_401(client):
    onboard(client)
    assert client.get("/telemetry/me", headers=auth("ccm_" + "x" * 43)).status_code == 401
    assert client.get("/telemetry/me", headers=auth("not-a-token")).status_code == 401


def test_me_shape(client):
    created = onboard(client)
    r = client.get("/telemetry/me", headers=auth(created["token"]))
    assert r.status_code == 200
    assert r.json() == {"id": created["id"], "label": "warner"}


def test_ingest_and_read_back(client):
    created = onboard(client)
    r = client.post(
        "/telemetry/ingest/exp-runs",
        json={"runs": [dict(ENTRY)]},
        headers=auth(created["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["accepted"]) == 1 and body["rejected"] == []

    r = client.get("/telemetry/exp/runs", headers=auth(created["token"]))
    runs = r.json()["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["map"] == "Cave of Evil Eye III"
    assert run["exp_per_hour"] == 109994.0
    assert run["net_per_hour"] == 66650.0
    assert run["run_id"] == body["accepted"][0]


def test_ingest_repost_is_idempotent(client, db):
    created = onboard(client)
    client.post("/telemetry/ingest/exp-runs", json={"runs": [dict(ENTRY)]}, headers=auth(created["token"]))
    grown = dict(ENTRY, exp=220000, seconds=7200.0)
    r = client.post(
        "/telemetry/ingest/exp-runs", json={"runs": [grown]}, headers=auth(created["token"])
    )
    assert r.status_code == 200
    rows = db.stores["maple_exp_runs"]
    assert len(rows) == 1 and rows[0]["exp"] == 220000


def test_ingest_reports_bad_rows_without_storing_them(client, db):
    created = onboard(client)
    r = client.post(
        "/telemetry/ingest/exp-runs",
        json={"runs": [dict(ENTRY), {"date": "nope"}]},
        headers=auth(created["token"]),
    )
    assert r.status_code == 200
    assert len(r.json()["accepted"]) == 1
    assert r.json()["rejected"][0]["index"] == 1
    assert len(db.stores["maple_exp_runs"]) == 1


def test_ingest_requires_runs_list(client):
    created = onboard(client)
    r = client.post(
        "/telemetry/ingest/exp-runs", json={"runs": "nope"}, headers=auth(created["token"])
    )
    assert r.status_code == 422


def test_runs_are_isolated_per_account(client):
    mine = onboard(client, "mine")
    theirs = onboard(client, "theirs")
    client.post("/telemetry/ingest/exp-runs", json={"runs": [dict(ENTRY)]}, headers=auth(mine["token"]))
    r = client.get("/telemetry/exp/runs", headers=auth(theirs["token"]))
    assert r.json()["runs"] == []
    r = client.get("/telemetry/exp/maps", headers=auth(theirs["token"]))
    assert r.json()["maps"] == []


def test_maps_endpoint_aggregates(client):
    created = onboard(client)
    client.post("/telemetry/ingest/exp-runs", json={"runs": [dict(ENTRY)]}, headers=auth(created["token"]))
    r = client.get("/telemetry/exp/maps", headers=auth(created["token"]))
    maps = r.json()["maps"]
    assert len(maps) == 1
    assert maps[0]["map"] == "Cave of Evil Eye III"
    assert maps[0]["best_exp_per_hour"] == 109994.0
    assert maps[0]["total_exp"] == 109994


def test_delete_account_retires_token_and_rows(client):
    created = onboard(client)
    client.post("/telemetry/ingest/exp-runs", json={"runs": [dict(ENTRY)]}, headers=auth(created["token"]))
    r = client.request("DELETE", "/telemetry/account", headers=auth(created["token"]))
    assert r.status_code == 200
    assert client.get("/telemetry/me", headers=auth(created["token"])).status_code == 401
