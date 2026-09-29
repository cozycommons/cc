"""In-process tests for the Resy MCP server: tool registration and behavior.

Tools run through FastMCP's in-memory call_tool; the supabase/account
boundaries are faked, so no network or database is touched.
"""

import asyncio
import json
from datetime import date, timedelta

import pytest

from resy import mcp_server

# Fixture reservations must stay "upcoming" no matter when the suite runs.
UPCOMING_DAY = (date.today() + timedelta(days=7)).isoformat()
from resy.accounts import AccountError


class FakeClient:
    SLOTS = [
        {
            "config": {"id": 2, "type": "Bar", "token": "rgs://b"},
            "date": {"start": "2026-09-28 19:30:00", "end": "2026-09-28 21:00:00"},
        },
    ]

    def search(self, query, lat, lng, day, party_size):
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
        return self.SLOTS

    def get_venue(self, venue_id):
        return {"name": "Lilia"}

    def get_user(self):
        return {
            "first_name": "Warner",
            "payment_methods": [
                {"id": 111, "brand": "visa", "last_four": "1234",
                 "is_default": True},
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


@pytest.fixture()
def wired(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    def fake_create_client(url, key):
        return object()

    def fake_get_account(supabase, token):
        if token == "ccr_A":
            return {"id": "acc-1", "label": "warner"}
        raise AccountError("invalid token")

    monkeypatch.setattr(mcp_server, "create_client", fake_create_client)
    monkeypatch.setattr(mcp_server.accounts, "get_account_by_token",
                        fake_get_account)
    monkeypatch.setattr(mcp_server.accounts, "make_client_for_account",
                        lambda supabase, account: FakeClient())
    return mcp_server.mcp


def call(server, tool, args):
    return asyncio.run(server._tool_manager.call_tool(tool, args))


def test_all_five_tools_registered(wired):
    names = sorted(t.name for t in wired._tool_manager.list_tools())
    assert names == [
        "book_table",
        "cancel_reservation",
        "check_availability",
        "list_reservations",
        "search_restaurants",
    ]


def test_search_restaurants(wired):
    out = json.loads(call(wired, "search_restaurants", {
        "api_token": "ccr_A", "query": "lilia",
        "location": "Long Island City", "day": "2026-09-28", "party_size": 2,
    }))
    assert out[0]["venue_id"] == 834
    assert out[0]["available_times"] == ["19:30"]


def test_check_availability(wired):
    out = json.loads(call(wired, "check_availability", {
        "api_token": "ccr_A", "venue_id": 834, "day": "2026-09-28",
    }))
    assert out["available_times"] == ["19:30"]
    assert out["slots"][0]["token"] == "rgs://b"


def test_list_reservations(wired):
    out = json.loads(call(wired, "list_reservations",
                          {"api_token": "ccr_A", "scope": "upcoming"}))
    assert [r["reservation_id"] for r in out] == [4242]


def test_book_table_names_masked_card(wired):
    out = json.loads(call(wired, "book_table", {
        "api_token": "ccr_A", "venue_id": 834, "date": "2026-09-28",
        "party_size": 2, "desired_time": "19:30",
    }))
    assert out["reservation_id"] == 7777
    assert out["payment_method"] == "Visa ....1234"


def test_cancel_by_token_and_confirmation(wired):
    out = json.loads(call(wired, "cancel_reservation", {
        "api_token": "ccr_A", "resy_token": "rr://a",
    }))
    assert out == {"cancelled": True, "resy_token": "rr://a"}
    out = json.loads(call(wired, "cancel_reservation", {
        "api_token": "ccr_A", "reservation_id": "4242",
    }))
    assert out == {"cancelled": True, "resy_token": "rr://a"}


def test_invalid_token_raises(wired):
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="invalid api_token"):
        call(wired, "search_restaurants", {"api_token": "bogus"})
