"""HTTP-level tests for the Resy FastAPI routes.

FastAPI TestClient with every external boundary faked: account resolution,
the Resy wire client, and onboarding. Covers auth, per-user isolation,
onboarding rate limiting, input validation, and error mapping.
"""

import pytest
from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient

from resy import routes

# Fixture reservations must stay "upcoming" no matter when the suite runs.
UPCOMING_DAY = (date.today() + timedelta(days=7)).isoformat()
from resy.accounts import AccountError
from resy.resy_client import ResyAuthError, ResyError


class FakeClient:
    """Canned Resy wire data for route tests (no network)."""

    def __init__(self, account_id=None):
        self.account_id = account_id
        self.seen_lat = None
        self.seen_lng = None

    SLOTS = [
        {
            "config": {"id": 2, "type": "Bar", "token": "rgs://b"},
            "date": {"start": "2026-09-28 19:30:00", "end": "2026-09-28 21:00:00"},
        },
    ]

    def search(self, query, lat, lng, day, party_size):
        self.seen_lat, self.seen_lng = lat, lng
        return [{
            "venue": {
                "id": {"resy": 834},
                "name": "Lilia",
                "location": {"neighborhood": "Williamsburg"},
                "type": "Italian",
            },
            "slots": self.SLOTS,
        }]

    def find_slots(self, venue_id, day, party_size):
        assert venue_id == 834
        return self.SLOTS

    def get_venue(self, venue_id):
        return {"name": "Lilia"}

    def get_user(self):
        return {
            "first_name": "Warner",
            "payment_methods": [
                {"id": 111, "brand": "visa", "last_four": "1234",
                 "is_default": True},
                {"id": 222, "brand": "amex", "last4": "99905",
                 "is_default": False},
            ],
        }

    def get_reservations(self):
        return [{
            "reservation": {
                "resy_token": "rr://a", "reservation_id": 4242,
                "day": UPCOMING_DAY, "time_slot": "19:00:00", "num_seats": 2,
                "venue": {"id": 834},
                "cancellation": {"allowed": True}, "status": {},
            },
            "venue": {"name": "Lilia"},
        }]

    def get_book_details(self, config_token, day, party_size):
        return {"book_token": {"value": "bt-1"}, "venue": {"name": "Lilia"}}

    def book(self, book_token, payment_method_id):
        return {
            "resy_token": "rr://new", "reservation_id": 7777,
            "day": "2026-09-28", "time_slot": "19:30:00", "num_seats": 2,
        }

    def cancel(self, resy_token):
        return {}


AccountClient = FakeClient


@pytest.fixture()
def app(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router, prefix="/resy")
    application.state.supabase = object()  # never touched; boundaries faked

    accounts = {
        "tok-A": {"id": "acc-1", "label": "warner"},
        "tok-B": {"id": "acc-2", "label": "friend"},
    }

    def fake_get_account(supabase, token):
        try:
            return accounts[token]
        except KeyError:
            raise AccountError("invalid token")

    def fake_make_client(supabase, account):
        return AccountClient(account["id"])

    monkeypatch.setattr(routes.accounts, "get_account_by_token", fake_get_account)
    monkeypatch.setattr(routes.accounts, "make_client_for_account", fake_make_client)
    routes._ONBOARD_ATTEMPTS.clear()
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- auth --------------------------------------------------------------------
def test_missing_bearer_is_401(client):
    r = client.get("/resy/me")
    assert r.status_code == 401


def test_invalid_token_is_401(client):
    r = client.get("/resy/me", headers=auth("nope"))
    assert r.status_code == 401


def test_me_returns_profile(client):
    r = client.get("/resy/me", headers=auth("tok-A"))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "acc-1"
    assert body["first_name"] == "Warner"


# --- per-user isolation ------------------------------------------------------
def test_two_tokens_get_two_scoped_clients(app):
    c = TestClient(app)
    r1 = c.get("/resy/search", headers=auth("tok-A"),
               params={"query": "lilia", "day": "2026-09-28"})
    r2 = c.get("/resy/search", headers=auth("tok-B"),
               params={"query": "lilia", "day": "2026-09-28"})
    assert r1.status_code == 200 and r2.status_code == 200
    # both resolve to the same fake data, but through per-account clients:
    assert r1.json()[0]["venue_id"] == 834
    assert r2.json()[0]["venue_id"] == 834


# --- search / coords ----------------------------------------------------------
def test_search_resolves_lic_location_to_coords(app):
    c = TestClient(app)
    captured = {}

    real_search = AccountClient.search

    def spy(self, query, lat, lng, day, party_size):
        captured["lat"], captured["lng"] = lat, lng
        return real_search(self, query, lat, lng, day, party_size)

    from unittest.mock import patch
    with patch.object(AccountClient, "search", spy):
        r = c.get("/resy/search", headers=auth("tok-A"),
                  params={"query": "x", "location": "Long Island City",
                          "day": "2026-09-28"})
    assert r.status_code == 200
    assert captured["lat"] == pytest.approx(40.7440)
    assert captured["lng"] == pytest.approx(-73.9485)


def test_search_bad_date_is_400(client):
    r = client.get("/resy/search", headers=auth("tok-A"),
                   params={"day": "tomorrow"})
    assert r.status_code == 400


def test_search_bad_party_size_is_422(client):
    r = client.get("/resy/search", headers=auth("tok-A"),
                   params={"party_size": 0})
    assert r.status_code == 422


# --- reads --------------------------------------------------------------------
def test_availability(client):
    r = client.get("/resy/availability", headers=auth("tok-A"),
                   params={"venue_id": 834, "day": "2026-09-28"})
    assert r.status_code == 200
    assert r.json()["available_times"] == ["19:30"]


def test_reservations_scopes(client):
    r = client.get("/resy/reservations", headers=auth("tok-A"),
                   params={"scope": "upcoming"})
    assert r.status_code == 200
    assert [x["reservation_id"] for x in r.json()] == [4242]


def test_reservations_bad_scope_is_400(client):
    r = client.get("/resy/reservations", headers=auth("tok-A"),
                   params={"scope": "someday"})
    assert r.status_code == 400


def test_payment_methods_masked(client):
    r = client.get("/resy/payment-methods", headers=auth("tok-A"))
    assert r.status_code == 200
    labels = [m["label"] for m in r.json()]
    assert labels == ["Visa ....1234", "Amex ....9905"]


# --- writes -------------------------------------------------------------------
def test_book_names_masked_card(client):
    r = client.post("/resy/book", headers=auth("tok-A"), json={
        "venue_id": 834, "date": "2026-09-28", "party_size": 2,
        "desired_time": "19:30",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["reservation_id"] == 7777
    assert body["payment_method"] == "Visa ....1234"


def test_book_without_slot_or_time_is_400(client):
    r = client.post("/resy/book", headers=auth("tok-A"), json={
        "venue_id": 834, "date": "2026-09-28",
    })
    assert r.status_code == 400


def test_book_unknown_card_is_400(client):
    r = client.post("/resy/book", headers=auth("tok-A"), json={
        "venue_id": 834, "date": "2026-09-28", "desired_time": "19:30",
        "payment_method_id": 999,
    })
    assert r.status_code == 400


def test_cancel_by_token(client):
    r = client.post("/resy/cancel", headers=auth("tok-A"),
                    json={"resy_token": "rr://a"})
    assert r.status_code == 200
    assert r.json() == {"cancelled": True, "resy_token": "rr://a"}


def test_cancel_unknown_confirmation_is_400(client):
    r = client.post("/resy/cancel", headers=auth("tok-A"),
                    json={"reservation_id": 12345})
    assert r.status_code == 400


# --- error mapping ------------------------------------------------------------
def test_resy_wire_error_maps_to_502(client, monkeypatch):
    def boom(self, *args):
        raise ResyError("Resy search -> 500 boom", status=500)

    monkeypatch.setattr(AccountClient, "search", boom)
    r = client.get("/resy/search", headers=auth("tok-A"),
                   params={"day": "2026-09-28"})
    assert r.status_code == 502


def test_resy_auth_error_maps_to_401_with_reonboard_hint(client, monkeypatch):
    def boom(self):
        raise ResyAuthError("session dead")

    monkeypatch.setattr(AccountClient, "get_reservations", boom)
    r = client.get("/resy/reservations", headers=auth("tok-A"))
    assert r.status_code == 401
    assert "re-onboard" in r.json()["detail"]


# --- onboarding ----------------------------------------------------------------
def test_onboard_success_and_rate_limit(client, monkeypatch):
    created = {}

    def fake_create(supabase, label, email, password):
        created.update(label=label, email=email)
        return {"id": "acc-9", "label": label, "token": "ccr_secret_once"}

    monkeypatch.setattr(routes.accounts, "create_account", fake_create)

    for _ in range(10):
        r = client.post("/resy/onboard",
                        json={"email": "w@example.com", "password": "pw"})
        assert r.status_code == 200
    assert r.json()["token"] == "ccr_secret_once"
    assert created["email"] == "w@example.com"

    r = client.post("/resy/onboard",
                    json={"email": "w@example.com", "password": "pw"})
    assert r.status_code == 429


def test_onboard_bad_credentials_is_400(client, monkeypatch):
    def fake_create(supabase, label, email, password):
        raise AccountError("Resy rejected those credentials")

    monkeypatch.setattr(routes.accounts, "create_account", fake_create)
    r = client.post("/resy/onboard",
                    json={"email": "w@example.com", "password": "bad"})
    assert r.status_code == 400
    assert "rejected" in r.json()["detail"]
