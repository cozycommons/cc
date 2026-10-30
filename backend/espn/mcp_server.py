"""MCP server for the ESPN Fantasy app — one integration point for every MCP-capable agent.

Mounted in main.py at /espn/mcp (Streamable HTTP). Tools take the caller's
personal API token (minted by POST /espn/onboard) as a parameter, so a single
server serves every friend; each call resolves the token to exactly one
account and only touches that account's ESPN league.

Deliberately no matchup-summary tool in v1. The one non-read tool surface
is the lineup run log (v2): daily lineup automation runs server-side under
the user's standing instructions, and get_lineup_runs exposes their plans
and conflicts here for on-demand pulling.

Roster edits (add/drop) are exposed as an explicit propose -> approve
pair mirroring the REST routes: propose_roster_edit validates and
persists a pending edit (submitting nothing), and approve_roster_edit is
the separate, deliberate call that executes it — the two calls are the
approval gate, never a single combined operation.

Trade proposals (propose_trade / approve_trade / get_trades) mirror
the same gate: approving submits a real trade offer to ESPN that the
counterparty sees, so the preview must be shown and explicitly
approved before the second call.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from supabase import create_client

from . import accounts
from . import lineup
from . import logic
from . import roster_edits
from . import snapshots
from . import trades
from .accounts import AccountError
from .scoreboard import ScoreboardClient

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


@mcp.tool()
def get_lineup_runs(
    api_token: str, limit: int = 25, scoring_period_id: int | None = None
) -> str:
    """Past automatic-lineup runs for your account, newest first.

    Each run carries its plan, the moves submitted, and its conflicts —
    a conflict means a scheduled player had to sit that day (slot
    overflow or eligibility jam), the cookies died (auth), or the
    submitted lineup failed verification. Pass scoring_period_id to
    pull up one specific day's run.
    """
    supabase, account, _ = _account_and_client(api_token)
    result = lineup.list_runs(supabase, account["id"], limit, scoring_period_id)
    return json.dumps(result)


@mcp.tool()
def run_lineup(
    api_token: str,
    date: str | None = None,
    scoring_period_id: int | None = None,
    dry_run: bool = False,
) -> str:
    """Set one day's lineup for your team (the shared run path).

    No target = the league's current scoring period (today). Pass a
    date (YYYY-MM-DD) or scoring_period_id to set any other day —
    future days can be set in advance, and runs are idempotent per
    day. The rule: every scheduled player starts; the run record it
    returns names any scheduled player who had to sit (a conflict).
    Use dry_run=true to preview the plan without submitting moves.
    """
    supabase, account, client = _account_and_client(api_token)
    result = lineup.run_lineup(
        supabase,
        account,
        client,
        dry_run=dry_run,
        scoring_period_id=scoring_period_id,
        date=date,
        scoreboard=ScoreboardClient(),
    )
    return json.dumps(result)


@mcp.tool()
def propose_roster_edit(
    api_token: str,
    add_player_id: int | None = None,
    drop_player_id: int | None = None,
) -> str:
    """Propose a roster add/drop for your team — SUBMITS NOTHING.

    Validates the edit against the live league (add target is a free
    agent, drop target is on your roster, post-edit roster is legal)
    and persists it as a pending edit with a validated snapshot, a
    human preview, and a 30-minute expiry. Pass both ids for a swap,
    or just one for an add-only / drop-only edit. The edit executes
    only when approve_roster_edit is called with the returned edit id
    — show the preview to the user and get their explicit approval
    before making that second call.
    """
    supabase, account, client = _account_and_client(api_token)
    result = roster_edits.propose_edit(
        supabase,
        account,
        client,
        add_player_id=add_player_id,
        drop_player_id=drop_player_id,
    )
    return json.dumps(result)


@mcp.tool()
def approve_roster_edit(api_token: str, edit_id: str) -> str:
    """Approve and execute ONE pending roster edit (the approval step).

    Executes the edit as a single ESPN transaction and records the
    outcome on the edit: executed, waiver_pending (the add became a
    waiver claim, bid 0), or failed with ESPN's error. Only call this
    after the user has explicitly approved the exact edit shown by
    propose_roster_edit. Approving an already-executed or expired
    edit is an error and never double-submits.
    """
    supabase, account, client = _account_and_client(api_token)
    result = roster_edits.approve_edit(
        supabase,
        account,
        client,
        edit_id,
        scoreboard=ScoreboardClient(),
    )
    return json.dumps(result)


@mcp.tool()
def get_roster_edits(
    api_token: str, limit: int = 25, edit_id: str | None = None
) -> str:
    """Roster edits for your account, newest first (the audit trail).

    Pass edit_id to fetch just that one edit's current status.
    """
    supabase, account, _ = _account_and_client(api_token)
    if edit_id is not None:
        edit = roster_edits.get_edit(supabase, account["id"], edit_id)
        if edit is None:
            raise ValueError("no roster edit with that id for this account")
        return json.dumps(edit)
    result = roster_edits.list_edits(supabase, account["id"], limit)
    return json.dumps(result)


@mcp.tool()
def propose_trade(
    api_token: str,
    counterparty_team_id: int,
    give_player_ids: list[int],
    receive_player_ids: list[int],
) -> str:
    """Propose a trade offer for your team — SUBMITS NOTHING.

    Validates the offer against the live league (counterparty exists
    and is not your own team, every give player is on your roster,
    every receive player is on theirs, the post-trade roster is legal
    for both teams, the trade deadline has not passed) and persists
    it as a pending proposal with snapshots of both sides, a human
    preview, and a 30-minute expiry. The offer reaches the
    counterparty only when approve_trade is called with the returned
    proposal id — show the preview to the user and get their explicit
    approval of that exact offer before making that second call,
    because approving submits a real offer the counterparty sees.
    """
    supabase, account, client = _account_and_client(api_token)
    result = trades.propose_trade(
        supabase,
        account,
        client,
        counterparty_team_id=counterparty_team_id,
        give_player_ids=give_player_ids,
        receive_player_ids=receive_player_ids,
    )
    return json.dumps(result)


@mcp.tool()
def approve_trade(api_token: str, proposal_id: str) -> str:
    """Approve and submit ONE pending trade proposal (the approval step).

    Submits the offer as a single ESPN TRADE transaction and records
    the outcome on the proposal: offered (ESPN accepted the offer; the
    counterparty accepts or declines on ESPN) or failed with ESPN's
    error. Only call this after the user has explicitly approved the
    exact offer shown by propose_trade. Approving an already-offered
    or expired proposal is an error and never double-submits.
    """
    supabase, account, client = _account_and_client(api_token)
    result = trades.approve_trade(
        supabase,
        account,
        client,
        proposal_id,
        scoreboard=ScoreboardClient(),
    )
    return json.dumps(result)


@mcp.tool()
def get_trades(
    api_token: str, limit: int = 25, proposal_id: str | None = None
) -> str:
    """Trade proposals for your account, newest first (the audit trail).

    Pass proposal_id to fetch just that one proposal's current status.
    """
    supabase, account, _ = _account_and_client(api_token)
    if proposal_id is not None:
        proposal = trades.get_proposal(supabase, account["id"], proposal_id)
        if proposal is None:
            raise ValueError(
                "no trade proposal with that id for this account"
            )
        return json.dumps(proposal)
    result = trades.list_proposals(supabase, account["id"], limit)
    return json.dumps(result)
