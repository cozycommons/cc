"""FastAPI routes for the Beli app. Mounted at /beli (see main.py).

Endpoints:
  POST /beli/onboard    create an account from a Beli login, mint an API token
  GET  /beli/me         check a token / describe the account
  GET  /beli/recs        ranked bookmarks first, then Beli trending
  POST /beli/bookmark    confidence-gated "Want to Try" bookmark write
  POST /beli/eats-ingest @beli_eats post ingestion (service key for all
                          opted-in accounts, or personal token for own account)
  POST /beli/eats/scan  enqueue a CC-orchestrated scan job (service key ->
                          scope 'all'; personal token -> own account)
  GET  /beli/eats/scan/pending  oldest pending scan job (polled by the
                          fetch box); 204 when the queue is empty
  POST /beli/eats/scan/{job_id}/complete  fetch box posts fetched IG posts;
                          CC runs the ingest pipeline under the job's scope
  GET  /beli/eats/scan/{job_id}  job status + the caller's digest slice
  GET  /beli/eats/digest   the caller's most recent completed scan digest

Scan jobs: CC never touches Instagram and accepts no inbound connections
from the fetch box. The box (a tiny service on the operator's VM) polls
/eats/scan/pending, fetches Instagram locally, and POSTs the posts back to
/eats/scan/{job_id}/complete. CC then runs the ingest pipeline and stores
the digest on the job row.

Auth: Authorization: Bearer <personal token> (from /beli/onboard).
Every request resolves the token to exactly one account and only ever touches
that account's Beli data.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import accounts
from . import eats_watcher
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


class EatsIngestPost(BaseModel):
    shortcode: str = Field(default="", max_length=128)
    created_at: str = Field(
        description="Post timestamp; ISO-8601 preferred, e.g. 2026-09-26T17:14:52+00:00",
        max_length=64,
    )
    post_caption: str = Field(default="", max_length=20000)


class EatsIngestBody(BaseModel):
    posts: list[EatsIngestPost] = Field(max_length=100)


class EatsScanCompleteBody(BaseModel):
    posts: list[EatsIngestPost] = Field(max_length=100)


def _ingest_service_key_ok(request: Request) -> bool:
    """Validate the harness service key for POST /beli/eats-ingest.

    Fail closed: missing server-side key never authenticates.
    """
    expected = os.environ.get("BELI_EATS_INGEST_KEY")
    if not expected:
        return False
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(token) and secrets.compare_digest(
        token, expected
    )


def _resolve_ingest_scope(request: Request) -> str | None:
    """Auth shared by /beli/eats-ingest and /beli/eats/scan.

    Returns None when the harness service key authenticated (run for every
    opted-in account), or the account id when a personal API token
    authenticated (run for the caller's account only). Raises 401 otherwise.
    """
    if _ingest_service_key_ok(request):
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise AccountError("missing bearer token")
        account = accounts.get_account_by_token(_supabase(request), token)
    except AccountError:
        raise HTTPException(status_code=401, detail="invalid service key or token")
    return account["id"]


def _run_ingest(
    supabase, posts: list, only_account_id: str | None = None
) -> list[dict]:
    """Shared ingest-processing core: runs the watch pipeline over `posts`
    and stamps each digest with the scan time."""
    digests = eats_watcher.run_eats_ingest(
        posts, supabase, only_account_id=only_account_id
    )
    scanned_at = datetime.now(timezone.utc).isoformat()
    for d in digests:
        d["scanned_at"] = scanned_at
    return digests


def _get_scan_job(supabase, job_id: str) -> dict:
    res = supabase.table("eats_scan_jobs").select("*").eq("id", job_id).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="unknown scan job")
    return rows[0]


def _job_includes(job: dict, account_id: str) -> bool:
    return job.get("scope") in ("all", account_id)


def _caller_digest_slice(digests: list, account_id: str) -> dict | None:
    for d in digests or []:
        if d.get("account_id") == account_id:
            return d
    return None


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


@router.post("/eats-ingest")
def eats_ingest(request: Request, body: EatsIngestBody):
    """Ingest @beli_eats posts fetched by the operator's harness.

    Two auth modes:
    - Harness service key (BELI_EATS_INGEST_KEY): runs the watch pipeline
      for every opted-in account and returns per-account digests.
    - Personal API token (ccb_... from /beli/onboard): runs the pipeline
      for the caller's account only. This lets a user's own harness job
      trigger ingestion without holding the shared service key.
    """
    posts = [p.model_dump() for p in body.posts]
    supabase = _supabase(request)
    only_account_id = _resolve_ingest_scope(request)
    digests = _run_ingest(supabase, posts, only_account_id)
    return {"accounts": len(digests), "digests": digests}


@router.post("/eats/scan", status_code=202)
def eats_scan(request: Request):
    """Enqueue a CC-orchestrated @beli_eats scan job.

    The fetch box polls GET /beli/eats/scan/pending for work, fetches
    Instagram locally, and POSTs the posts back to
    /beli/eats/scan/{job_id}/complete. Same auth modes as /beli/eats-ingest:
    the harness service key creates a job scoped to every opted-in account
    ('all'); a personal API token scopes the job to the caller's account.
    """
    only_account_id = _resolve_ingest_scope(request)
    scope = "all" if only_account_id is None else only_account_id
    res = (
        _supabase(request)
        .table("eats_scan_jobs")
        .insert({"scope": scope, "status": "pending"})
        .execute()
    )
    job_id = (res.data or [{}])[0].get("id")
    return {"job_id": job_id, "status": "queued"}


@router.get("/eats/scan/pending")
def eats_scan_pending(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Oldest pending scan job, for the fetch-box poller.

    Only reveals work-to-do (job id + scope), never user data.
    """
    res = (
        _supabase(request)
        .table("eats_scan_jobs")
        .select("id,scope")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return Response(status_code=204)
    return {"job_id": rows[0]["id"], "scope": rows[0]["scope"]}


@router.post("/eats/scan/{job_id}/complete")
def eats_scan_complete(
    job_id: str,
    body: EatsScanCompleteBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Complete a scan job with posts fetched by the fetch box.

    CC runs the shared ingest pipeline under the job's stored scope: 'all'
    fans out to every opted-in account via CC's internal authority (the
    poller never holds the service key); otherwise only the scoped account.
    The resulting digest(s) are stored on the job row.
    """
    supabase = _supabase(request)
    job = _get_scan_job(supabase, job_id)
    if job.get("status") != "pending":
        raise HTTPException(status_code=409, detail="job is not pending")
    supabase.table("eats_scan_jobs").update({"status": "running"}).eq(
        "id", job_id
    ).execute()
    posts = [p.model_dump() for p in body.posts]
    scope = job.get("scope")
    only_account_id = None if scope == "all" else scope
    try:
        digests = _run_ingest(supabase, posts, only_account_id)
    except Exception as e:  # noqa: BLE001 - recorded on the job, then reported
        supabase.table("eats_scan_jobs").update(
            {"status": "failed", "error": str(e)[:500]}
        ).eq("id", job_id).execute()
        raise HTTPException(status_code=502, detail=f"ingest failed: {e}")
    supabase.table("eats_scan_jobs").update(
        {"status": "done", "digest": digests}
    ).eq("id", job_id).execute()
    return {"job_id": job_id, "status": "done", "digests": digests}


@router.get("/eats/scan/{job_id}")
def eats_scan_status(
    job_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Scan job status. The digest is filtered to the caller's own account."""
    job = _get_scan_job(_supabase(request), job_id)
    if not _job_includes(job, account["id"]):
        raise HTTPException(status_code=403, detail="not your scan job")
    out: dict = {"job_id": job_id, "status": job.get("status")}
    if job.get("digest") is not None:
        out["digest"] = _caller_digest_slice(job["digest"], account["id"])
    if job.get("error"):
        out["error"] = job["error"]
    return out


@router.get("/eats/digest")
def eats_digest(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """The caller's most recent completed @beli_eats scan digest."""
    res = (
        _supabase(request)
        .table("eats_scan_jobs")
        .select("scope,digest")
        .eq("status", "done")
        .order("created_at", desc=True)
        .execute()
    )
    for job in res.data or []:
        if not _job_includes(job, account["id"]):
            continue
        digest = _caller_digest_slice(job.get("digest"), account["id"])
        if digest:
            return digest
    raise HTTPException(status_code=404, detail="no scan yet")
