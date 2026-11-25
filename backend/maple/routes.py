"""FastAPI routes for Maple telemetry. Mounted at /telemetry (see main.py).

Endpoints:
  POST   /telemetry/onboard         mint a telemetry account + token
  GET    /telemetry/me              check a token / describe the account
  DELETE /telemetry/account         delete the caller's account (+ its rows)
  POST   /telemetry/ingest/exp-runs ship EXP overlay log entries (batch)
  GET    /telemetry/exp/runs        the account's runs, newest first
  GET    /telemetry/exp/maps        per-map aggregates, best rate first

Onboarding mints a personal token ("ccm_..."), shown ONCE in the response:
  POST /onboard {"label?"} -> {"id", "label", "token"}
There are no third-party credentials in this module; the token is the
account. The shipper on the player's machine holds it in a local config
file and presents it as a bearer token on ingest.

Auth: Authorization: Bearer <personal token> (from /onboard). Every
request resolves the token to exactly one account and only ever touches
that account's rows. Token resolution reads through the uncached
app.state.maple_supabase client, so a deleted account's token stops
working on the next request (docs/security.md).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import accounts, logic
from .accounts import AccountError
from .logic import RunError

logger = logging.getLogger(__name__)

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# --- onboarding rate limit: 10 attempts per IP per hour (mirrors ESPN) -------
_ONBOARD_ATTEMPTS: dict[str, list[float]] = {}
_ONBOARD_LIMIT = 10
_ONBOARD_WINDOW_S = 3600


def _onboard_rate_check(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _ONBOARD_ATTEMPTS.get(ip, []) if now - t < _ONBOARD_WINDOW_S]
    if len(attempts) >= _ONBOARD_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many onboarding attempts; try again later"
        )
    attempts.append(now)
    _ONBOARD_ATTEMPTS[ip] = attempts


def _supabase(request: Request):
    # Token reads must never go through CachedSupabaseClient
    # (app.state.supabase); main.py provides the uncached maple client.
    return getattr(request.app.state, "maple_supabase", None) or request.app.state.supabase


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


@router.post("/onboard")
def onboard(request: Request, body: dict = Body(default={})):
    _onboard_rate_check(request.client.host if request.client else "unknown")
    label = body.get("label") if isinstance(body, dict) else None
    if label is not None and not isinstance(label, str):
        raise HTTPException(status_code=422, detail="label must be a string")
    try:
        return accounts.create_account(_supabase(request), label)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
def me(account: dict = Depends(_account)):
    return {"id": account["id"], "label": account["label"]}


@router.delete("/account")
def delete_account(request: Request, account: dict = Depends(_account)):
    accounts.delete_account(_supabase(request), account["id"])
    return {"deleted": account["id"]}


@router.post("/ingest/exp-runs")
def ingest_exp_runs(
    request: Request, body: dict = Body(...), account: dict = Depends(_account)
):
    runs = body.get("runs") if isinstance(body, dict) else None
    try:
        return logic.ingest_runs(_supabase(request), account["id"], runs)
    except RunError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/exp/runs")
def exp_runs(
    request: Request,
    account: dict = Depends(_account),
    limit: int = Query(default=25, ge=1, le=200),
    map: str | None = Query(default=None),
    level: int | None = Query(default=None),
):
    return {
        "runs": logic.list_runs(
            _supabase(request), account["id"], limit=limit, map_name=map, level=level
        )
    }


@router.get("/exp/maps")
def exp_maps(
    request: Request,
    account: dict = Depends(_account),
    level: int | None = Query(default=None),
):
    return {"maps": logic.map_stats(_supabase(request), account["id"], level=level)}
