"""FastAPI routes for the ESPN Fantasy app. Mounted at /espn (see main.py).

Endpoints:
  POST /espn/onboard          store ESPN cookies, mint an API token
  GET  /espn/me               check a token / describe the account
  GET  /espn/league           league settings + slim teams
  GET  /espn/standings        teams ranked by wins, then points for
  GET  /espn/teams/{team_id}  one team + its roster
  GET  /espn/transactions     recent transactions (player ids only)
  GET  /espn/trends/players   ownership + performance trends (snapshot-based)
  GET  /espn/trends/teams     per-team form / all-play / luck trends
  GET  /espn/draft            draft picks in overall-pick order
  POST /espn/automation/lineup  opt in/out of daily lineup automation
  POST /espn/lineup/run       set today's lineup now (or dry-run a plan)
  GET  /espn/lineup/runs      past lineup runs + their conflicts

There is deliberately no /matchups endpoint in v1.

The lineup endpoints are v2: fully automatic daily lineup setting under
the user's standing instructions (see espn/lineup.py). Lineup moves
only — there are no add/drop/trade endpoints.

Onboarding stores the caller's ESPN cookies (espn_s2 + SWID) encrypted at
rest (see accounts.py):
  POST /onboard {label?, league_id, season, espn_s2, swid}
      -> {"id", "label", "league_id", "season", "token"}
The token is shown ONCE.

Auth: Authorization: Bearer <personal token> (from /onboard).
Every request resolves the token to exactly one account and only ever touches
that account's ESPN league. An EspnAuthError from ESPN (expired cookies) maps
to 401 — the detail tells the user to re-onboard.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from . import lineup
from . import logic
from . import snapshots
from .accounts import AccountError
from .espn_client import EspnAuthError, EspnError
from .public_predictions import router as public_predictions_router
from .scoreboard import ScoreboardClient
from .team_claims import router as team_claims_router

router = APIRouter()
router.include_router(public_predictions_router)
router.include_router(team_claims_router)
_bearer = HTTPBearer(auto_error=False)

# --- onboarding rate limit: 10 attempts per IP per hour ----------------------
_ONBOARD_ATTEMPTS: dict[str, list[float]] = {}
_ONBOARD_LIMIT = 10
_ONBOARD_WINDOW_S = 3600


def _onboard_rate_check(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _ONBOARD_ATTEMPTS.get(ip, []) if now - t < _ONBOARD_WINDOW_S]
    if len(attempts) >= _ONBOARD_LIMIT:
        raise HTTPException(status_code=429, detail="too many onboarding attempts; try again later")
    attempts.append(now)
    _ONBOARD_ATTEMPTS[ip] = attempts


def _supabase(request: Request):
    return request.app.state.supabase


def _account(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),  # noqa: B008
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return accounts.get_account_by_token(_supabase(request), creds.credentials)
    except AccountError:
        raise HTTPException(status_code=401, detail="invalid token")


def _client(account: dict):
    return accounts.make_client_for_account(account)


# --- snapshot span -------------------------------------------------------------


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
    """Days between the two newest snapshots' captured_at values, or None.

    ensure_snapshot returns the current snapshot's captured_at but not the
    previous one's, so the span is derived here from latest_snapshots —
    snapshots' own interface is left untouched.
    """
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


# --- models ------------------------------------------------------------------
class OnboardBody(BaseModel):
    label: str = Field(default="espn", max_length=80)
    league_id: int = Field(description="ESPN fantasy league id")
    season: int = Field(description="Season year, e.g. 2027")
    espn_s2: str = Field(description="espn_s2 cookie value")
    swid: str = Field(description="SWID cookie value, e.g. {XXXXXXXX-...}")


# --- endpoints ---------------------------------------------------------------
@router.post("/onboard")
def onboard(body: OnboardBody, request: Request):
    """Store the ESPN cookies, and mint a personal API token.

    The returned token is shown ONCE — it cannot be retrieved later.
    """
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    try:
        return accounts.create_account(
            _supabase(request),
            body.label,
            body.league_id,
            body.season,
            body.espn_s2,
            body.swid,
        )
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/me")
def me(account: dict = Depends(_account)):  # noqa: B008
    return {
        "id": account.get("id"),
        "label": account.get("label"),
        "league_id": account.get("league_id"),
        "season": account.get("season"),
        "lineup_automation_enabled": bool(
            account.get("lineup_automation_enabled")
        ),
    }


@router.get("/league")
def league(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """League settings plus a slim team list."""
    client = _client(account)
    try:
        return logic.get_league(client)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/standings")
def standings(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Teams ranked by wins (desc), then points for (desc)."""
    client = _client(account)
    try:
        return logic.get_standings(client)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teams/{team_id}")
def team_detail(
    team_id: int,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """One team plus its roster."""
    client = _client(account)
    try:
        return logic.get_team(client, team_id)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/transactions")
def transactions(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    limit: int = Query(default=25, description="Max transactions, 1-200"),
):
    """Recent league transactions, newest first (player ids only)."""
    client = _client(account)
    try:
        return logic.get_transactions(client, limit)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trends/players")
def player_trends(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    limit: int = Query(default=10, description="Max entries per trend list"),
):
    """Player ownership + performance trends from league snapshots.

    The first call captures a snapshot and falls back to ESPN's own
    percent-change / last-7-days splits; later calls compare snapshots.
    """
    client = _client(account)
    try:
        return _player_trends(_supabase(request), account, client, limit)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trends/teams")
def team_trends(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Per-team trends, live from the schedule (its own time series)."""
    client = _client(account)
    try:
        return logic.get_team_trends(client)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/draft")
def draft(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Draft picks in overall-pick order."""
    client = _client(account)
    try:
        return logic.get_draft(client)
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- lineup automation (v2) ----------------------------------------------------


class AutomationBody(BaseModel):
    enabled: bool = Field(description="Opt in/out of daily lineup automation")


class LineupRunBody(BaseModel):
    dry_run: bool = Field(
        default=False,
        description="Compute and record the plan without submitting moves",
    )
    scoring_period_id: int | None = Field(
        default=None,
        description="Scoring period (day) to set; defaults to the league's current",
    )
    date: str | None = Field(
        default=None,
        description="Target day as YYYY-MM-DD, resolved against the "
        "league's scoring periods; ignored when scoring_period_id is set",
    )


@router.post("/automation/lineup")
def set_lineup_automation(
    body: AutomationBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Opt this account in/out of automatic lineup setting."""
    enabled = accounts.set_lineup_automation(
        _supabase(request), account["id"], body.enabled
    )
    return {"lineup_automation_enabled": enabled}


@router.post("/lineup/run")
def lineup_run(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    body: LineupRunBody | None = Body(default=None),  # noqa: B008
):
    """Set one day's lineup for this account now (the shared run path).

    No target = the league's current scoring period. A ``date``
    (YYYY-MM-DD) or ``scoring_period_id`` targets any other day —
    ESPN allows setting future days' lineups in advance, and runs are
    idempotent per (account, scoring period).

    The run — plan, moves, conflicts, errors — is recorded either way
    and returned; ESPN failures are reported in the run's status/error
    fields (auth failure -> status "auth_error"), not as HTTP errors.
    """
    body = body or LineupRunBody()
    if body.date is not None:
        try:
            datetime.strptime(body.date, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="date must be YYYY-MM-DD"
            )
    client = _client(account)
    return lineup.run_lineup(
        _supabase(request),
        account,
        client,
        dry_run=body.dry_run,
        scoring_period_id=body.scoring_period_id,
        date=body.date,
        scoreboard=ScoreboardClient(),
    )


@router.get("/lineup/runs")
def lineup_runs(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    limit: int = Query(default=25, description="Max runs, 1-200"),
    scoring_period_id: int | None = Query(
        default=None, description="Only runs for this scoring period"
    ),
):
    """Past lineup runs for this account, newest first, with conflicts."""
    try:
        return lineup.list_runs(
            _supabase(request), account["id"], limit, scoring_period_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
