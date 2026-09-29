"""Unit tests for Resy logic: slimming, slot matching, payment labels, writes.

A fake ResyClient stands in for the wire — no network, no account needed.
"""

import pytest
from datetime import date, timedelta

from resy import logic

# Fixture reservations must stay "upcoming" no matter when the suite runs.
UPCOMING_DAY = (date.today() + timedelta(days=7)).isoformat()


class FakeClient:
    def __init__(self):
        self.booked = []
        self.cancelled = []

    # -- canned data ------------------------------------------------------
    SLOTS = [
        {
            "config": {"id": 1, "type": "Dining Room", "token": "rgs://a"},
            "date": {"start": "2026-09-28 18:00:00", "end": "2026-09-28 19:30:00"},
            "payment": {"cancellation_fee": 25},
        },
        {
            "config": {"id": 2, "type": "Bar", "token": "rgs://b"},
            "date": {"start": "2026-09-28 19:30:00", "end": "2026-09-28 21:00:00"},
        },
    ]
    VENUES = [
        {
            "venue": {
                "id": {"resy": 834},
                "name": "Lilia",
                "location": {"neighborhood": "Williamsburg", "locality": "Brooklyn"},
                "type": "Italian",
                "price_range": 3,
                "rating": 4.8,
            },
            "slots": SLOTS,
        }
    ]

    def search(self, query, lat, lng, day, party_size):
        return self.VENUES

    def find_slots(self, venue_id, day, party_size):
        assert venue_id == 834
        return self.SLOTS

    def get_venue(self, venue_id):
        return self.VENUES[0]["venue"]

    def get_user(self):
        return {
            "first_name": "Warner",
            "payment_methods": [
                {
                    "id": 111,
                    "brand": "visa",
                    "last_four": "1234",
                    "exp_month": 4,
                    "exp_year": 2028,
                    "is_default": True,
                },
                {
                    "id": 222,
                    "brand": "amex",
                    "last4": "99905",
                    "is_default": False,
                },
            ],
        }

    def get_reservations(self):
        return [
            {
                "reservation": {
                    "resy_token": "rr://a",
                    "reservation_id": 4242,
                    "day": UPCOMING_DAY,
                    "time_slot": "19:00:00",
                    "num_seats": 2,
                    "venue": {"id": 834},
                    "cancellation": {"allowed": True},
                    "status": {},
                },
                "venue": {"name": "Lilia"},
            },
            {
                "reservation": {
                    "resy_token": "rr://old",
                    "reservation_id": 1111,
                    "day": "2026-09-01",
                    "time_slot": "20:00:00",
                    "num_seats": 4,
                    "venue": {"id": 834},
                    "status": {"finished": 1},
                },
                "venue": {"name": "Lilia"},
            },
        ]

    def get_book_details(self, config_token, day, party_size):
        return {
            "book_token": {"value": "bt-1"},
            "venue": {"name": "Lilia"},
        }

    def book(self, book_token, payment_method_id):
        self.booked.append((book_token, payment_method_id))
        return {
            "resy_token": "rr://new",
            "reservation_id": 7777,
            "day": "2026-09-28",
            "time_slot": "19:30:00",
            "num_seats": 2,
        }

    def cancel(self, resy_token):
        self.cancelled.append(resy_token)
        return {}


@pytest.fixture()
def client():
    return FakeClient()


# --- reads -------------------------------------------------------------------
def test_search_slims_venues(client):
    (v,) = logic.search_restaurants(client, "lilia", 40.7, -73.9, "2026-09-28", 2)
    assert v["venue_id"] == 834
    assert v["name"] == "Lilia"
    assert v["neighborhood"] == "Williamsburg"
    assert v["available_times"] == ["18:00", "19:30"]
    assert v["slots"][0]["token"] == "rgs://a"
    assert v["slots"][0]["start"] == "18:00"  # HH:MM, no TZ shift
    assert v["slots"][0]["cancellation_fee"] == 25


def test_search_validates_inputs(client):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        logic.search_restaurants(client, "x", 0, 0, "tomorrow", 2)
    with pytest.raises(ValueError, match="party_size"):
        logic.search_restaurants(client, "x", 0, 0, "2026-09-28", 0)


def test_check_availability(client):
    out = logic.check_availability(client, 834, "2026-09-28", 2)
    assert out["venue_name"] == "Lilia"
    assert out["available_times"] == ["18:00", "19:30"]
    with pytest.raises(ValueError, match="venue_id"):
        logic.check_availability(client, "abc", "2026-09-28", 2)


def test_list_reservations_scopes(client):
    upcoming = logic.list_reservations(client, "upcoming")
    assert [r["reservation_id"] for r in upcoming] == [4242]
    assert upcoming[0]["time"] == "19:00"
    assert upcoming[0]["cancellable"] is True
    past = logic.list_reservations(client, "past")
    assert [r["reservation_id"] for r in past] == [1111]
    assert past[0]["status"] == "finished"
    assert len(logic.list_reservations(client, "all")) == 2
    with pytest.raises(ValueError, match="scope"):
        logic.list_reservations(client, "bogus")


def test_payment_methods_masked(client):
    (default, other) = logic.list_payment_methods(client)
    assert default["id"] == 111
    assert default["label"] == "Visa ....1234"
    assert default["is_default"] is True
    assert other["label"] == "Amex ....9905"  # last4 fallback, last 4 digits


def test_masked_card_label_edge_cases():
    assert logic.masked_card_label({"brand": "visa"}) == "Visa"
    assert logic.masked_card_label({}) == "Card"


# --- writes ------------------------------------------------------------------
def test_book_by_desired_time_uses_default_card(client):
    out = logic.book_table(client, 834, "2026-09-28", 2, desired_time="19:30")
    assert out["resy_token"] == "rr://new"
    assert out["reservation_id"] == 7777
    assert out["venue_name"] == "Lilia"
    assert out["time"] == "19:30"
    assert out["payment_method"] == "Visa ....1234"
    assert out["payment_method_id"] == 111
    assert client.booked == [("bt-1", 111)]


def test_book_by_slot_token_and_explicit_card(client):
    out = logic.book_table(
        client, 834, "2026-09-28", 2, slot_token="rgs://a", payment_method_id=222
    )
    assert out["payment_method"] == "Amex ....9905"
    assert client.booked == [("bt-1", 222)]


def test_book_no_matching_slot_lists_available(client):
    with pytest.raises(ValueError, match="available: 18:00, 19:30"):
        logic.book_table(client, 834, "2026-09-28", 2, desired_time="21:00")


def test_book_needs_time_or_token(client):
    with pytest.raises(ValueError, match="slot_token or desired_time"):
        logic.book_table(client, 834, "2026-09-28", 2)


def test_book_rejects_unknown_card(client):
    with pytest.raises(ValueError, match="unknown payment_method_id"):
        logic.book_table(client, 834, "2026-09-28", 2,
                         desired_time="19:30", payment_method_id=999)


def test_book_requires_card_on_file(monkeypatch, client):
    monkeypatch.setattr(client, "get_user", lambda: {"payment_methods": []})
    with pytest.raises(ValueError, match="No payment method on file"):
        logic.book_table(client, 834, "2026-09-28", 2, desired_time="19:30")


def test_cancel_by_token(client):
    out = logic.cancel_reservation(client, resy_token="rr://a")
    assert out == {"cancelled": True, "resy_token": "rr://a"}
    assert client.cancelled == ["rr://a"]


def test_cancel_by_confirmation_number_resolves_token(client):
    out = logic.cancel_reservation(client, reservation_id=4242)
    assert out == {"cancelled": True, "resy_token": "rr://a"}


def test_cancel_unknown_confirmation_number(client):
    with pytest.raises(ValueError, match="no reservation found"):
        logic.cancel_reservation(client, reservation_id=12345)


def test_cancel_needs_an_identifier(client):
    with pytest.raises(ValueError, match="resy_token or reservation_id"):
        logic.cancel_reservation(client)
