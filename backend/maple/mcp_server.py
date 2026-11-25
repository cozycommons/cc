"""MCP server for Maple telemetry — one integration point for agents.

Mounted in main.py at /telemetry/mcp (Streamable HTTP). Tools take the
caller's personal API token (minted by POST /telemetry/onboard) as a
parameter, mirroring the /espn/mcp pattern: a single server serves every
account, and each call resolves the token to exactly one account and only
touches that account's rows. All tools are reads.
"""

from __future__ import annotations

import json
import os

from mcp_validation import FastMCP
from supabase import create_client

from . import accounts, logic
from .accounts import AccountError

mcp = FastMCP("maple")


def _account(api_token: str):
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    try:
        account = accounts.get_account_by_token(supabase, api_token)
    except AccountError as e:
        raise ValueError(f"invalid api_token: {e}")
    return supabase, account


@mcp.tool()
def get_me(api_token: str) -> str:
    """The telemetry account this token belongs to (id + label)."""
    _, account = _account(api_token)
    return json.dumps({"id": account["id"], "label": account["label"]})


@mcp.tool()
def get_recent_exp_runs(api_token: str, limit: int = 25) -> str:
    """Recent EXP overlay log lines for your account, newest first.

    Each run is one day/map/level/class/party log line with its totals
    and the overlay's rates: exp_per_hour, mesos_per_hour, net_per_hour
    (net is null when no potion cost was counted for the line).
    """
    supabase, account = _account(api_token)
    return json.dumps({"runs": logic.list_runs(supabase, account["id"], limit=limit)})


@mcp.tool()
def get_exp_runs_by_map(api_token: str, map: str, limit: int = 25) -> str:
    """EXP log lines for one exact map name, newest first."""
    supabase, account = _account(api_token)
    return json.dumps(
        {"runs": logic.list_runs(supabase, account["id"], limit=limit, map_name=map)}
    )


@mcp.tool()
def get_best_exp_rates(api_token: str, level: int | None = None, limit: int = 10) -> str:
    """Per-map EXP rates across your logged runs, best first.

    best_exp_per_hour is the best single log line on the map;
    avg_exp_per_hour is time-weighted (total EXP / total time). Pass
    level to restrict to runs logged at that level.
    """
    supabase, account = _account(api_token)
    maps = logic.map_stats(supabase, account["id"], level=level)
    return json.dumps({"maps": maps[: max(1, min(int(limit), 100))]})
