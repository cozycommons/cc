"""FastAPI routes for the Beli app. Mounted at /beli (see main.py).

Endpoints:
  POST /beli/onboard    create an account from a Beli login, mint an API token
  GET  /beli/me         check a token / describe the account
  GET  /beli/recs        ranked bookmarks first, then Beli trending
  POST /beli/bookmark    confidence-gated "Want to Try" bookmark write

Auth: Authorization: Bearer <personal token> (from /beli/onboard).
Every request resolves the token to exactly one account and only ever touches
that account's Beli data.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from .accounts import AccountError
from .beli_client import BeliClient, BeliError
from .logic import bookmark_name, get_recs

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


# --- models ------------------------------------------------------------------
class OnboardBody(BaseModel):
    label: str = Field(default="beli", max_length=80)
    beli_id: str = Field(description="Beli email or phone number, e.g. +15551234567")
    password: str = Field(description="Beli password")


class BookmarkBody(BaseModel):
    name: str = Field(description='Restaurant name, e.g. "Table Mercato"')
    city: str | None = Field(default=None, description='City hint, e.g. "New York, NY"')
    dry_run: bool = Field(default=False, description="Resolve the match without writing")


# --- endpoints ---------------------------------------------------------------
@router.post("/onboard")
def onboard(body: OnboardBody, request: Request):
    """Create a Beli account entry and mint a personal API token.

    The Beli login is validated live before anything is stored. The returned
    token is shown ONCE — it cannot be retrieved later.
    """
    ip = (request.client.host if request.client else "unknown") or "unknown"
    _onboard_rate_check(ip)
    try:
        return accounts.create_account(
            _supabase(request), body.label, body.beli_id, body.password
        )
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
def me(account: dict = Depends(_account)):  # noqa: B008
    return {
        "id": account["id"],
        "label": account["label"],
        "watcher_opt_in": account["watcher_opt_in"],
    }


@router.get("/recs")
def recs(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    neighborhood: str = Query(..., description='e.g. "Greenwich Village"'),
    day: str | None = Query(default=None, description='YYYY-MM-DD or "Saturday"'),
    time: str | None = Query(default=None, description='"19:00" / "7pm"'),
    table_size: int = Query(default=2, ge=1, le=20),
    limit: int = Query(default=10, ge=1, le=20),
):
    """Restaurant recommendations: your bookmarks (by your scores) first,
    then Beli trending to fill. Each rec carries hours, open-at-time status,
    and reservation slots/platforms."""
    client = accounts.make_client_for_account(account)
    try:
        return get_recs(client, neighborhood, day, time, table_size, limit)
    except (BeliError, ValueError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/bookmark")
def bookmark(
    body: BookmarkBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Bookmark a restaurant to your Beli "Want to Try".

    Only an exact/near-exact name match writes; anything ambiguous returns
    status "ambiguous" with candidates and writes nothing. Already-bookmarked
    and already-ranked places are reported, never duplicated.
    """
    client = accounts.make_client_for_account(account)
    try:
        return bookmark_name(client, body.name, body.city, body.dry_run)
    except (BeliError, ValueError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/watcher-opt-in")
def watcher_opt_in(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    enabled: bool = Query(default=True),
):
    """Opt in/out of the @beli_eats auto-bookmark watcher for your account."""
    _supabase(request).table("beli_accounts").update(
        {"watcher_opt_in": bool(enabled)}
    ).eq("id", account["id"]).execute()
    return {"watcher_opt_in": bool(enabled)}
