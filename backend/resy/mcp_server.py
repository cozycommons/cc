"""MCP server for the Resy app — one integration point for every MCP-capable agent.

Mounted in main.py at /resy/mcp (Streamable HTTP). Tools take the caller's
personal API token (minted by POST /resy/onboard) as a parameter, so a single
server serves every friend; each call resolves the token to exactly one
account and only touches that account's Resy data.

Writes (book_table, cancel_reservation) are approval-gated at the agent
layer: the agent confirms venue, date, time, party size, and the masked card
with the user before calling. The backend enforces per-user scoping.
"""

from __future__ import annotations

import json
import os
from datetime import date

from mcp.server.fastmcp import FastMCP
from supabase import create_client

from . import accounts, logic
from .accounts import AccountError

mcp = FastMCP("resy")


def _client_for_token(api_token: str):
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    try:
        account = accounts.get_account_by_token(supabase, api_token)
    except AccountError as e:
        raise ValueError(f"invalid api_token: {e}")
    return accounts.make_client_for_account(supabase, account)


@mcp.tool()
def search_restaurants(
    api_token: str,
    query: str = "",
    location: str = "New York",
    day: str = "",
    party_size: int = 2,
) -> str:
    """Search Resy restaurants near a location, with that day's slots baked in.

    query: venue name or cuisine, e.g. "ramen". location: e.g. "Long Island
    City", "manhattan", or a city name. day: YYYY-MM-DD (default today).
    Returns venues with venue_id, neighborhood, rating, and available_times.
    """
    from .routes import _coords_for

    client = _client_for_token(api_token)
    lat, lng = _coords_for(location, None, None)
    result = logic.search_restaurants(
        client, query, lat, lng, day or date.today().isoformat(), party_size
    )
    return json.dumps(result)


@mcp.tool()
def check_availability(
    api_token: str, venue_id: int, day: str, party_size: int = 2
) -> str:
    """Available time slots at one Resy venue for a day.

    venue_id: numeric Resy venue id (from search_restaurants). day: YYYY-MM-DD.
    Each slot carries a token (the rgs:// config token) usable for booking.
    """
    client = _client_for_token(api_token)
    result = logic.check_availability(client, venue_id, day, party_size)
    return json.dumps(result)


@mcp.tool()
def list_reservations(api_token: str, scope: str = "upcoming") -> str:
    """List your Resy reservations. scope: "upcoming" (default), "past", "all"."""
    client = _client_for_token(api_token)
    result = logic.list_reservations(client, scope)
    return json.dumps(result)


@mcp.tool()
def book_table(
    api_token: str,
    venue_id: int,
    date: str,
    party_size: int = 2,
    desired_time: str = "",
    slot_token: str = "",
    payment_method_id: int = 0,
) -> str:
    """Book a table on Resy. APPROVAL-GATED: confirm venue, date, time, party
    size, and the masked card with the user before calling.

    Pick the slot by desired_time ("HH:MM", e.g. "19:30") or by the exact
    slot_token from check_availability. payment_method_id: a saved card id;
    omit (0) to use the account default. The response names the masked card
    used ("Visa ....1234").
    """
    client = _client_for_token(api_token)
    result = logic.book_table(
        client,
        venue_id,
        date,
        party_size,
        desired_time=desired_time or None,
        slot_token=slot_token or None,
        payment_method_id=payment_method_id or None,
    )
    return json.dumps(result)


@mcp.tool()
def cancel_reservation(
    api_token: str, resy_token: str = "", reservation_id: str = ""
) -> str:
    """Cancel a Resy reservation by resy_token (rr://...) or numeric
    confirmation number. APPROVAL-GATED: confirm with the user before calling.
    """
    client = _client_for_token(api_token)
    rid = None
    if reservation_id:
        try:
            rid = int(reservation_id)
        except ValueError:
            rid = reservation_id
    result = logic.cancel_reservation(
        client, resy_token=resy_token or None, reservation_id=rid
    )
    return json.dumps(result)
