"""MCP server for the Beli app — one integration point for every MCP-capable agent.

Mounted in main.py at /beli/mcp (Streamable HTTP). Tools take the caller's
personal API token (minted by POST /beli/onboard) as a parameter, so a single
server serves every friend; each call resolves the token to exactly one
account and only touches that account's Beli data.
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP
from supabase import create_client

from . import accounts
from .accounts import AccountError
from .logic import bookmark_name, get_recs

mcp = FastMCP("beli")


def _client_for_token(api_token: str):
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    try:
        account = accounts.get_account_by_token(supabase, api_token)
    except AccountError as e:
        raise ValueError(f"invalid api_token: {e}")
    return accounts.make_client_for_account(account)


@mcp.tool()
def get_recs(
    api_token: str,
    neighborhood: str,
    day: str = "",
    time: str = "",
    table_size: int = 2,
    limit: int = 10,
) -> str:
    """Restaurant recommendations for a neighborhood.

    Returns your bookmarked spots (ranked by your Beli scores) first, then
    Beli trending to fill. Each rec has hours, open-at-time status, and
    reservation slots/platforms. day: YYYY-MM-DD or "Saturday". time: "7pm".
    """
    client = _client_for_token(api_token)
    result = get_recs(
        client,
        neighborhood,
        day or None,
        time or None,
        table_size,
        limit,
    )
    return json.dumps(result)


@mcp.tool()
def bookmark_restaurant(
    api_token: str, name: str, city: str = "", dry_run: bool = False
) -> str:
    """Save a restaurant to your Beli "Want to Try" list.

    Only an exact/near-exact name match writes; ambiguous names return
    status "ambiguous" with candidates and write nothing. Already-saved or
    already-ranked places are reported, never duplicated.
    """
    client = _client_for_token(api_token)
    result = bookmark_name(client, name, city or None, dry_run)
    return json.dumps(result)
