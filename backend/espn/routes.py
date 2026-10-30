"""FastAPI routes for the ESPN Fantasy app. Mounted at /espn (see main.py).

Endpoints:
  POST /espn/onboard          store ESPN cookies, mint an API token
  POST /espn/onboard/login    log in with email+password, mint a token
  GET  /espn/me               check a token / describe the account
  GET  /espn/league           league settings + slim teams
  GET  /espn/standings        teams ranked by wins, then points for
  GET  /espn/teams/{team_id}  one team + its roster
  GET  /espn/transactions     recent transactions (player ids only)
  GET  /espn/trends/players   ownership + performance trends (snapshot-based)
  GET  /espn/trends/teams     per-team form / all-play / luck trends
  GET  /espn/waivers          waiver wire: FA form, pocket picks, drops
  GET  /espn/draft            draft picks in overall-pick order
  POST /espn/automation/lineup  opt in/out of daily lineup automation
  POST /espn/lineup/run       set today's lineup now (or dry-run a plan)
  GET  /espn/lineup/runs      past lineup runs + their conflicts
  POST /espn/roster/edits     propose a roster add/drop (validates +
                              persists a pending edit; submits nothing)
  POST /espn/roster/edits/{id}/approve
                              approve + execute one pending edit as a
                              single ESPN transaction
  GET  /espn/roster/edits     the account's roster edits (audit trail)
  GET  /espn/roster/edits/{id}  one roster edit
  POST /espn/trades           propose a trade offer (validates +
                              persists a pending proposal; submits
                              nothing)
  POST /espn/trades/{id}/approve
                              approve + submit one pending proposal's
                              offer as a single ESPN transaction
  GET  /espn/trades           the account's trade proposals (audit)
  GET  /espn/trades/{id}      one trade proposal
  DELETE /espn/account        delete the caller's account (+ cascaded history)

There is deliberately no /matchups endpoint in v1.

The lineup endpoints are v2: fully automatic daily lineup setting under
the user's standing instructions (see espn/lineup.py). The roster-edit
endpoints are the module's other write: approval-gated add/drop (see
espn/roster_edits.py) — an edit is proposed, validated and persisted
first, and only an explicit approve call executes it. Trade proposals
follow the identical gate (see espn/trades.py): proposed and
validated first, and only an explicit approve call submits the offer
to ESPN, where the counterparty can accept or decline it.

Onboarding stores the caller's ESPN cookies (espn_s2 + SWID) encrypted at
rest (see accounts.py):
  POST /onboard {label?, league_id, season, espn_s2, swid}
      -> {"id", "label", "league_id", "season", "token"}
The token is shown ONCE.

There is also a login front door for users who can't extract cookies:
  POST /onboard/login {email, password, label?, league_id?, season?,
                       enable_automation?}
The backend runs the MyDisney login once (see disney_login.py), discovers
the account's basketball leagues, and feeds the harvested cookies into the
same store path. The password is used once and never stored or logged.
With several leagues and no league_id, nothing is created; the response
is {"status": "league_selection_required", "leagues": [...]} and the
client re-submits with the chosen league_id.

Auth: Authorization: Bearer <personal token> (from /onboard).
Every request resolves the token to exactly one account and only ever touches
that account's ESPN league. An EspnAuthError from ESPN (expired cookies) maps
to 401 — the detail tells the user to re-onboard.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from . import disney_login
from . import lineup
from . import logic
from . import roster_edits
from . import snapshots
from . import trades
from . import waivers as waivers_logic
from .accounts import AccountError
from .espn_client import EspnAuthError, EspnClient, EspnError
from .public_predictions import router as public_predictions_router
from .scoreboard import ScoreboardClient
from .team_claims import router as team_claims_router
from .fantasy_admin import router as fantasy_admin_router

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(public_predictions_router)
router.include_router(team_claims_router)
router.include_router(fantasy_admin_router)
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


# --- login onboarding ----------------------------------------------------------


class OnboardLoginBody(BaseModel):
    email: str = Field(description="ESPN account email (MyDisney login)")
    password: str = Field(
        description="ESPN account password — used once to log in, never stored"
    )
    label: str = Field(default="espn", max_length=80)
    league_id: int | None = Field(
        default=None,
        description="League to onboard; omit to auto-discover the "
        "account's basketball leagues for the season",
    )
    season: int | None = Field(
        default=None,
        description="Season (ending) year; defaults to the current "
        "season by the July 1 rollover",
    )
    enable_automation: bool = Field(
        default=False,
        description="Deprecated and ignored: lineup automation is "
        "enabled for every new account at onboarding; opt out via "
        "POST /espn/automation/lineup",
    )


def _default_season() -> int:
    """Current NBA season (ending year): rolls over on July 1 (UTC).

    The same rule team_claims applies to snapshot seasons.
    """
    now = datetime.now(timezone.utc)
    return now.year + (1 if now.month >= 7 else 0)


def _league_echo(espn_s2: str, swid: str, league_id: int, season: int) -> dict:
    """Best-effort league/team names for the onboarding response.

    The account is already created when this runs, so a failure here
    must never fail the request (that would strand the minted token) —
    the names are a confirmation nicety, not part of the contract.
    """
    try:
        payload = EspnClient(espn_s2, swid, league_id, season).get_league(
            ["mSettings", "mTeam"]
        )
    except EspnError:
        return {}
    echo = {"league_name": (payload.get("settings") or {}).get("name")}
    try:
        team = lineup.find_member_team(payload, swid)
    except ValueError:
        return echo
    echo["team_id"] = team.get("id")
    echo["team_name"] = logic._team_name(team)
    return echo


@router.post("/onboard/login")
def onboard_login(body: OnboardLoginBody, request: Request):
    """Onboard by logging in to ESPN with email + password.

    Runs the MyDisney login exactly once (the password is never stored
    or logged), discovers the account's basketball leagues for the
    season, and stores the harvested cookies through the same path as
    cookie onboarding. Outcomes map to stable detail codes the hosted
    form renders: invalid_credentials (401), account_not_found (404),
    challenge_required (403), disney_unavailable (502),
    league_discovery_failed (502), no_league_found (400).
    """
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    if not body.email.strip() or not body.password:
        raise HTTPException(status_code=400, detail="email_and_password_required")
    season = body.season or _default_season()
    try:
        cookies = disney_login.login(body.email, body.password)
    except disney_login.InvalidCredentialsError:
        logger.warning("espn onboard/login failed: outcome=invalid_credentials")
        raise HTTPException(status_code=401, detail="invalid_credentials")
    except disney_login.AccountNotFoundError:
        logger.warning("espn onboard/login failed: outcome=account_not_found")
        raise HTTPException(status_code=404, detail="account_not_found")
    except disney_login.ChallengeRequiredError:
        logger.warning("espn onboard/login failed: outcome=challenge_required")
        raise HTTPException(status_code=403, detail="challenge_required")
    except disney_login.DisneyLoginError:
        logger.warning("espn onboard/login failed: outcome=disney_unavailable")
        raise HTTPException(status_code=502, detail="disney_unavailable")
    espn_s2, swid = cookies["espn_s2"], cookies["swid"]

    if body.league_id is not None:
        league_id = body.league_id
    else:
        try:
            leagues = disney_login.discover_basketball_leagues(
                espn_s2, swid, season
            )
        except disney_login.DisneyLoginError:
            logger.warning(
                "espn onboard/login failed: outcome=league_discovery_failed"
            )
            raise HTTPException(status_code=502, detail="league_discovery_failed")
        if not leagues:
            logger.warning("espn onboard/login failed: outcome=no_league_found")
            raise HTTPException(status_code=400, detail="no_league_found")
        if len(leagues) > 1:
            # Create nothing yet — the client asks the user to pick.
            logger.info(
                "espn onboard/login: league selection required (%d leagues)",
                len(leagues),
            )
            return {
                "status": "league_selection_required",
                "season": season,
                "leagues": [
                    {
                        "league_id": entry["league_id"],
                        "name": entry["name"],
                        "team_name": entry["team_name"],
                    }
                    for entry in leagues
                ],
            }
        league_id = leagues[0]["league_id"]

    try:
        created = accounts.create_account(
            _supabase(request),
            body.label,
            league_id,
            season,
            espn_s2,
            swid,
        )
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Automation is part of onboarding: create_account stored the
    # account with lineup_automation_enabled = true (product decision,
    # 2026-10-29), so there is no post-create opt-in step here. The
    # opt-out / re-enable switch is POST /espn/automation/lineup.
    automation = True
    logger.info(
        "espn onboard/login ok: account=%s league=%s automation=%s",
        created.get("id"),
        league_id,
        automation,
    )
    return {
        **created,
        "lineup_automation_enabled": automation,
        **_league_echo(espn_s2, swid, league_id, season),
    }


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


@router.delete("/account")
def delete_account(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Delete the caller's own account (self-service disconnect).

    The bearer token resolved to exactly this account, so a token can
    only ever delete its own account. The stored ESPN cookies, the
    token itself, the snapshot history and the lineup run log all go
    with the row (snapshots/runs cascade; see accounts.delete_account).
    """
    accounts.delete_account(_supabase(request), account["id"])
    logger.info("espn account deleted: account=%s", account.get("id"))
    return {"deleted": True, "id": account.get("id")}


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


@router.get("/waivers")
def waiver_wire(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Waiver-wire report: free-agent form, pocket picks, drop candidates.

    Live-computed from the account's league (see espn/waivers.py): the
    top free agents by last-15-days fantasy points per game under the
    league's own scoring, a deterministic low-ownership pocket-pick
    subset with reasons, and the account's own coldest healthy players.
    Read-only — no ESPN writes.
    """
    client = _client(account)
    try:
        return waivers_logic.get_waivers(
            client, account.get("swid"), scoreboard=ScoreboardClient()
        )
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


# --- roster edits (approval-gated add/drop) ------------------------------------


class RosterEditBody(BaseModel):
    add_player_id: int | None = Field(
        default=None,
        description="ESPN player id to add; omit for a drop-only edit",
    )
    drop_player_id: int | None = Field(
        default=None,
        description="ESPN player id to drop; omit for an add-only edit",
    )


@router.post("/roster/edits")
def propose_roster_edit(
    body: RosterEditBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Propose a roster add/drop for this account (submits NOTHING).

    The edit is validated against the live league — the add target is
    a free agent, the drop target is on the caller's own roster, and
    the post-edit roster is legal — and persisted as a pending edit
    with the validated snapshot, a human preview, and a 30-minute
    expiry. Executing it takes a separate POST to
    /espn/roster/edits/{id}/approve; that two-step gate is the point.
    """
    client = _client(account)
    try:
        return roster_edits.propose_edit(
            _supabase(request),
            account,
            client,
            add_player_id=body.add_player_id,
            drop_player_id=body.drop_player_id,
        )
    except roster_edits.EditError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/roster/edits/{edit_id}/approve")
def approve_roster_edit(
    edit_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Approve and execute one pending roster edit.

    Executes the edit as ONE ESPN transaction and records the outcome
    on the edit (executed / waiver_pending / failed). Approving an
    edit that is not pending (already executed, failed, or expired)
    is a 409, and an edit belonging to another account is a 404 —
    approving twice never double-submits.
    """
    client = _client(account)
    try:
        return roster_edits.approve_edit(
            _supabase(request),
            account,
            client,
            edit_id,
            scoreboard=ScoreboardClient(),
        )
    except roster_edits.EditNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except roster_edits.EditStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/roster/edits")
def list_roster_edits(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    limit: int = Query(default=25, description="Max edits, 1-200"),
    status: str | None = Query(
        default=None, description="Only edits in this status"
    ),
):
    """Past roster edits for this account, newest first (audit trail)."""
    try:
        return roster_edits.list_edits(
            _supabase(request), account["id"], limit, status
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/roster/edits/{edit_id}")
def get_roster_edit(
    edit_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """One roster edit for this account (404 when it is not theirs)."""
    edit = roster_edits.get_edit(_supabase(request), account["id"], edit_id)
    if edit is None:
        raise HTTPException(
            status_code=404, detail="no roster edit with that id for this account"
        )
    return edit


# --- trades (approval-gated trade proposals) -----------------------------------


class TradeBody(BaseModel):
    counterparty_team_id: int = Field(
        description="ESPN team id to trade with (not your own team)"
    )
    give_player_ids: list[int] = Field(
        description="ESPN player ids you give up (all on your roster)"
    )
    receive_player_ids: list[int] = Field(
        description="ESPN player ids you receive (all on their roster)"
    )


@router.post("/trades")
def propose_trade(
    body: TradeBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Propose a trade offer for this account (submits NOTHING).

    The offer is validated against the live league — the counterparty
    exists and is not the caller's own team, every give player is on
    the caller's roster, every receive player is on the counterparty's
    roster, the post-trade roster is legal for both teams, and the
    trade deadline has not passed — and persisted as a pending
    proposal with both sides' snapshots, a human preview, and a
    30-minute expiry. Submitting the offer to ESPN takes a separate
    POST to /espn/trades/{id}/approve; that two-step gate is the
    point, because approval sends a real offer the counterparty sees.
    """
    client = _client(account)
    try:
        return trades.propose_trade(
            _supabase(request),
            account,
            client,
            counterparty_team_id=body.counterparty_team_id,
            give_player_ids=body.give_player_ids,
            receive_player_ids=body.receive_player_ids,
        )
    except trades.TradeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades/{proposal_id}/approve")
def approve_trade(
    proposal_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Approve and submit one pending trade proposal's offer.

    Submits the offer as ONE ESPN TRADE transaction and records the
    outcome on the proposal (offered / failed); whether the
    counterparty accepts happens later, on ESPN. Approving a proposal
    that is not pending (already offered, failed, or expired) is a
    409, and a proposal belonging to another account is a 404 —
    approving twice never double-submits.
    """
    client = _client(account)
    try:
        return trades.approve_trade(
            _supabase(request),
            account,
            client,
            proposal_id,
            scoreboard=ScoreboardClient(),
        )
    except trades.TradeNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except trades.TradeStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except EspnAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except EspnError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades")
def list_trades(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    limit: int = Query(default=25, description="Max proposals, 1-200"),
    status: str | None = Query(
        default=None, description="Only proposals in this status"
    ),
):
    """Past trade proposals for this account, newest first (audit trail)."""
    try:
        return trades.list_proposals(
            _supabase(request), account["id"], limit, status
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades/{proposal_id}")
def get_trade(
    proposal_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """One trade proposal for this account (404 when it is not theirs)."""
    proposal = trades.get_proposal(
        _supabase(request), account["id"], proposal_id
    )
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="no trade proposal with that id for this account",
        )
    return proposal
