"""MCP server for the ESPN Fantasy app — one integration point for every MCP-capable agent.

Mounted in main.py at /espn/mcp (Streamable HTTP). Tools take the caller's
personal API token (minted by POST /espn/onboard) as a parameter, so a single
server serves every friend; each call resolves the token to exactly one
account and only touches that account's ESPN league.

Read-only: no write tools, and deliberately no matchup-summary tool in v1.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from supabase import create_client

from . import accounts
from . import logic
from . import snapshots
from .accounts import AccountError

mcp = FastMCP("espn")


def _account_and_client(api_token: str):
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    )
    try:
        account = accounts.get_account_by_token(supabase, api_token)
    except AccountError as e:
        raise ValueError(f"invalid api_token: {e}")
    client = accounts.make_client_for_account(account)
    return supabase, account, client


def _parse_captured_at(row) -> datetime | None:
    if not isinstance(row, dict):
        return None
    value = row.get("captured_at")
    if value is None:
        for key in ("snapshot", "payload"):
            nested = row.get(key)
            if isinstance(nested, dict) and nested.get("captured_at") is not None:
                value = nested.get("captured_at")
                break
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _snapshot_span_days(supabase, account: dict) -> float | None:
    """Days between the two newest snapshots' captured_at values, or None."""
    try:
        rows = snapshots.latest_snapshots(supabase, account.get("id"), limit=2)
    except Exception:
        return None
    if not rows or len(rows) < 2:
        return None
    current_at = _parse_captured_at(rows[0])
    previous_at = _parse_captured_at(rows[1])
    if current_at is None or previous_at is None:
        return None
    return (current_at - previous_at).total_seconds() / 86400


def _player_trends(supabase, account: dict, client, limit: int) -> dict:
    snap = snapshots.ensure_snapshot(supabase, account, client)
    span_days = _snapshot_span_days(supabase, account)
    current = snap.get("current") if isinstance(snap, dict) else None
    previous = snap.get("previous") if isinstance(snap, dict) else None
    return {
        "ownership": logic.player_ownership_trends(current, previous, limit),
        "performance": logic.player_performance_trends(
            current, previous, span_days, limit
        ),
        "snapshot": {
            "captured_at": snap.get("captured_at") if isinstance(snap, dict) else None,
            "fresh_capture": snap.get("fresh_capture")
            if isinstance(snap, dict)
            else None,
            "history": previous is not None,
        },
    }


@mcp.tool()
def get_league(api_token: str) -> str:
    """League settings plus a slim team list for your ESPN fantasy league."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_league(client)
    return json.dumps(result)


@mcp.tool()
def get_standings(api_token: str) -> str:
    """League standings: teams ranked by wins, then points for."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_standings(client)
    return json.dumps(result)


@mcp.tool()
def get_team(api_token: str, team_id: int) -> str:
    """One team plus its roster, by numeric ESPN team id."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_team(client, team_id)
    return json.dumps(result)


@mcp.tool()
def get_transactions(api_token: str, limit: int = 25) -> str:
    """Recent league transactions, newest first (player ids only; 1-200)."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_transactions(client, limit)
    return json.dumps(result)


@mcp.tool()
def get_player_trends(api_token: str, limit: int = 10) -> str:
    """Player ownership + performance trends from league snapshots.

    The first call captures a snapshot and falls back to ESPN's own
    percent-change / last-7-days splits; later calls compare snapshots.
    """
    supabase, account, client = _account_and_client(api_token)
    result = _player_trends(supabase, account, client, limit)
    return json.dumps(result)


@mcp.tool()
def get_team_trends(api_token: str) -> str:
    """Per-team trends: weekly points, last-3 average, all-play wins, luck."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_team_trends(client)
    return json.dumps(result)


@mcp.tool()
def get_draft(api_token: str) -> str:
    """Draft picks in overall-pick order, with team names resolved."""
    _, _, client = _account_and_client(api_token)
    result = logic.get_draft(client)
    return json.dumps(result)
