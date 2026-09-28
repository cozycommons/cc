"""FastAPI routes for the Partiful app. Mounted at /partiful (see main.py).

Endpoints (all read-only):
  POST /partiful/onboard/start  send the SMS verification code to a phone number
  POST /partiful/onboard/verify verify the SMS code, store the account, mint an API token
  GET  /partiful/me             check a token / describe the account
  GET  /partiful/events         the caller's events (hosted + RSVP'd + invited)
  GET  /partiful/events/{id}    detail for one event

Onboarding is a two-step Firebase phone-auth flow because the user must read
the SMS code off their own phone:
  1. POST /onboard/start {phone} -> {"status": "code_sent", "phone": "+1..."}
  2. POST /onboard/verify {phone, code, label?} -> {"id", "label", "token"}
The token is shown ONCE.

Auth: Authorization: Bearer <personal token> (from /onboard/verify).
Every request resolves the token to exactly one account and only ever touches
that account's Partiful data.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from . import logic
from .accounts import AccountError
from .partiful_client import PartifulClient, PartifulError

router = APIRouter()
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


def _client(request: Request, account: dict) -> PartifulClient:
    return accounts.make_client_for_account(_supabase(request), account)


# --- models ------------------------------------------------------------------
class OnboardStartBody(BaseModel):
    phone: str = Field(description="Phone number, e.g. 8185551234 or +18185551234")


class OnboardVerifyBody(BaseModel):
    phone: str = Field(description="Same phone number used in /onboard/start")
    code: str = Field(description="SMS verification code")
    label: str = Field(default="partiful", max_length=80)


# --- endpoints ---------------------------------------------------------------
@router.post("/onboard/start")
def onboard_start(body: OnboardStartBody, request: Request):
    """Send the Partiful SMS verification code to a phone number."""
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    try:
        phone = accounts.normalize_phone(body.phone)
    except PartifulError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        PartifulClient.send_auth_code(phone)
    except PartifulError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "code_sent", "phone": phone}


@router.post("/onboard/verify")
def onboard_verify(body: OnboardVerifyBody, request: Request):
    """Verify the SMS code, store the account, and mint a personal API token.

    The returned token is shown ONCE — it cannot be retrieved later.
    """
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    try:
        return accounts.create_account(
            _supabase(request), body.label, body.phone, body.code
        )
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PartifulError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/me")
def me(account: dict = Depends(_account)):  # noqa: B008
    return {"id": account["id"], "label": account["label"]}


@router.get("/events")
def events(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    scope: str = Query(
        default="all",
        description="all | hosted | rsvps | invited",
    ),
    start: str | None = Query(
        default=None, description="Start date filter, YYYY-MM-DD (inclusive)"
    ),
    end: str | None = Query(
        default=None, description="End date filter, YYYY-MM-DD (inclusive)"
    ),
):
    """The caller's Partiful events: hosted, RSVP'd, and invited.

    scope=all merges hosted events with every invited/RSVP'd event,
    deduplicated by event id and tagged with "scopes". Each event carries the
    caller's own RSVP status when Partiful reports one.
    """
    client = _client(request, account)
    try:
        return logic.list_events(client, scope, start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PartifulError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/events/{event_id}")
def event_detail(
    event_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Detail for one viewable event."""
    client = _client(request, account)
    try:
        return logic.get_event(client, event_id)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
    except PartifulError as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="event not found")
        raise HTTPException(status_code=502, detail=str(e))
