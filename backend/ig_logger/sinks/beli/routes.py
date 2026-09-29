"""FastAPI routes for the Beli app (an ig_logger sink). Mounted at /beli.

The Beli app is the first application on the ig_logger platform: it
watches the @beli_eats Instagram source and auto-bookmarks confident
restaurant mentions into each opted-in account's Beli "Want to Try".

Endpoints:
  POST /beli/onboard    create an account from a Beli login, mint an API token
  GET  /beli/me         check a token / describe the account
  GET  /beli/recs        ranked bookmarks first, then Beli trending
  POST /beli/bookmark    confidence-gated "Want to Try" bookmark write
  POST /beli/watcher-opt-in  toggle the @beli_eats auto-bookmark watcher
  POST /beli/eats-ingest @beli_eats post ingestion (DEPRECATED: manual
                          backfills only; prefer the scan-job queue)
  POST /beli/eats/scan  enqueue a scan job for @beli_eats (service key ->
                          scope 'all'; personal token -> own account)
  GET  /beli/eats/scan/pending  oldest pending @beli_eats scan job (polled
                          by the fetch box); 204 when the queue is empty
  POST /beli/eats/scan/{job_id}/complete  fetch box posts fetched IG posts;
                          CC runs the ingest pipeline under the job's scope
  GET  /beli/eats/scan/{job_id}  job status + the caller's digest slice
  GET  /beli/eats/digest   the caller's most recent completed scan digest

The /beli/eats/* endpoints are thin wrappers over the ig_logger platform
(scan jobs for source 'beli_eats'); response shapes are unchanged.

Auth: Authorization: Bearer <personal token> (from /beli/onboard).
Every request resolves the token to exactly one account and only ever touches
that account's Beli data.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ... import jobs as scan_jobs
from ... import runner, sources
from ...auth import resolve_scan_scope
from . import accounts
from .accounts import AccountError
from .beli_client import BeliClient, BeliError
from .logic import bookmark_name, get_recs

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

# The Instagram source this app watches.
SOURCE_HANDLE = "beli_eats"

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


# --- legacy digest helpers ---------------------------------------------------
def _legacy_digest(platform_digest: dict | None) -> dict | None:
    """Flatten one platform digest to the historical /beli/eats/* shape."""
    if not platform_digest:
        return None
    sink_digest = (platform_digest.get("sinks") or {}).get("beli")
    if not sink_digest:
        return None
    return {
        **sink_digest,
        "account_id": platform_digest.get("account_id"),
        "scanned_at": platform_digest.get("scanned_at"),
    }


def _legacy_digests(platform_digests: list[dict]) -> list[dict]:
    out = []
    for d in platform_digests or []:
        leg = _legacy_digest(d)
        if leg:
            out.append(leg)
    return out


def _caller_legacy_slice(job: dict, account_id: str) -> dict | None:
    for d in job.get("digest") or []:
        if d.get("account_id") == account_id:
            return _legacy_digest(d)
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
    supabase = _supabase(request)
    supabase.table("beli_accounts").update(
        {"watcher_opt_in": bool(enabled)}
    ).eq("id", account["id"]).execute()
    # Keep the platform source subscription in sync with the Beli sink flag.
    sources.set_enabled(supabase, account["id"], SOURCE_HANDLE, bool(enabled))
    return {"watcher_opt_in": bool(enabled)}


@router.post("/eats-ingest")
def eats_ingest(request: Request, response: Response, body: EatsIngestBody):
    """Ingest @beli_eats posts fetched by the operator's harness.

    DEPRECATED: prefer the scan-job queue (POST /beli/eats/scan). This
    endpoint is retained for manual backfills only.

    Two auth modes:
    - Harness service key (BELI_EATS_INGEST_KEY): runs the watch pipeline
      for every subscribed account and returns per-account digests.
    - Personal API token (ccb_... from /beli/onboard): runs the pipeline
      for the caller's account only. This lets a user's own harness job
      trigger ingestion without holding the shared service key.
    """
    response.headers["Deprecation"] = "true"
    posts = [p.model_dump() for p in body.posts]
    supabase = _supabase(request)
    only_account_id = resolve_scan_scope(request)
    digests = runner.run_ingest(supabase, posts, SOURCE_HANDLE, only_account_id)
    return {"accounts": len(digests), "digests": _legacy_digests(digests)}


@router.post("/eats/scan", status_code=202)
def eats_scan(request: Request):
    """Enqueue a CC-orchestrated @beli_eats scan job.

    The fetch box polls GET /beli/eats/scan/pending for work, fetches
    Instagram locally, and POSTs the posts back to
    /beli/eats/scan/{job_id}/complete. Same auth modes as /beli/eats-ingest:
    the harness service key creates a job scoped to every subscribed account
    ('all'); a personal API token scopes the job to the caller's account.
    """
    only_account_id = resolve_scan_scope(request)
    scope = "all" if only_account_id is None else only_account_id
    return scan_jobs.create_job(_supabase(request), SOURCE_HANDLE, scope)


@router.get("/eats/scan/pending")
def eats_scan_pending(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Oldest pending @beli_eats scan job, for the fetch-box poller.

    Only reveals work-to-do (job id + scope), never user data.
    """
    job = scan_jobs.oldest_pending(_supabase(request), SOURCE_HANDLE)
    if not job:
        return Response(status_code=204)
    return job


@router.post("/eats/scan/{job_id}/complete")
def eats_scan_complete(
    job_id: str,
    body: EatsScanCompleteBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Complete a scan job with posts fetched by the fetch box.

    CC runs the shared ingest pipeline under the job's stored scope: 'all'
    fans out to every subscribed account via CC's internal authority (the
    poller never holds the service key); otherwise only the scoped account.
    The resulting digest(s) are stored on the job row.
    """
    supabase = _supabase(request)
    job = scan_jobs.get_job(supabase, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown scan job")
    if job.get("status") != "pending":
        raise HTTPException(status_code=409, detail="job is not pending")
    scan_jobs.mark_running(supabase, job_id)
    posts = [p.model_dump() for p in body.posts]
    scope = job.get("scope")
    only_account_id = None if scope == "all" else scope
    try:
        digests = runner.run_ingest(
            supabase, posts, job.get("source_handle") or SOURCE_HANDLE, only_account_id
        )
    except Exception as e:  # noqa: BLE001 - recorded on the job, then reported
        scan_jobs.mark_failed(supabase, job_id, str(e))
        raise HTTPException(status_code=502, detail=f"ingest failed: {e}")
    scan_jobs.mark_done(supabase, job_id, digests)
    return {"job_id": job_id, "status": "done", "digests": _legacy_digests(digests)}


@router.get("/eats/scan/{job_id}")
def eats_scan_status(
    job_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Scan job status. The digest is filtered to the caller's own account."""
    job = scan_jobs.get_job(_supabase(request), job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown scan job")
    if not scan_jobs.job_includes(job, account["id"]):
        raise HTTPException(status_code=403, detail="not your scan job")
    out: dict = {"job_id": job_id, "status": job.get("status")}
    if job.get("digest") is not None:
        out["digest"] = _caller_legacy_slice(job, account["id"])
    if job.get("error"):
        out["error"] = job["error"]
    return out


@router.get("/eats/digest")
def eats_digest(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """The caller's most recent completed @beli_eats scan digest."""
    job = scan_jobs.latest_done_for_account(
        _supabase(request), account["id"], SOURCE_HANDLE
    )
    if not job:
        raise HTTPException(status_code=404, detail="no scan yet")
    digest = _caller_legacy_slice(job, account["id"])
    if digest:
        return digest
    raise HTTPException(status_code=404, detail="no scan yet")
