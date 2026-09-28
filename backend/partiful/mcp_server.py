"""MCP server for the Partiful app — one integration point for every MCP-capable agent.

Mounted in main.py at /partiful/mcp (Streamable HTTP). Tools take the caller's
personal API token (minted by POST /partiful/onboard/verify) as a parameter,
so a single server serves every friend; each call resolves the token to
exactly one account and only touches that account's Partiful data.

Read-only: no write tools.
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP
from supabase import create_client

from . import accounts
from .accounts import AccountError
from .logic import get_event, list_events

mcp = FastMCP("partiful")


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
def list_events(
    api_token: str, scope: str = "all", start: str = "", end: str = ""
) -> str:
    """List your Partiful events.

    scope: "all" (hosted + RSVP'd + invited, deduplicated), "hosted",
    "rsvps" (you responded), or "invited" (every invite, any status).
    start/end: optional YYYY-MM-DD bounds on the event date, e.g. to pull
    "this past weekend" pass the Saturday and Sunday dates.
    """
    client = _client_for_token(api_token)
    result = list_events(client, scope, start or None, end or None)
    return json.dumps(result)


@mcp.tool()
def get_event(api_token: str, event_id: str) -> str:
    """Detail for one Partiful event by id."""
    client = _client_for_token(api_token)
    result = get_event(client, event_id)
    return json.dumps(result)
