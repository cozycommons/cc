"""Platform routes for ig_logger (mounted at /ig-logger).

Source subscriptions are per-user (personal token). Scan jobs use the
dual auth model: the harness service key creates platform-wide ('all')
jobs, a personal token scopes the job to the caller's account.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import jobs, runner, sources
from .accounts import AccountError, get_account_row_by_token
from .auth import resolve_scan_scope

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _supabase(request: Request):
    return request.app.state.supabase


def _account(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),  # noqa: B008
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return get_account_row_by_token(_supabase(request), creds.credentials)
    except AccountError:
        raise HTTPException(status_code=401, detail="invalid token")


class SourceBody(BaseModel):
    handle: str = Field(description="Instagram handle, e.g. 'beli_eats'")


class ScanPost(BaseModel):
    created_at: str = ""
    post_caption: str = Field(default="", max_length=20000)


class ScanBody(BaseModel):
    source_handle: str = Field(description="Instagram handle to fetch")


class ScanCompleteBody(BaseModel):
    posts: list[ScanPost] = Field(max_length=100)


# --- source subscriptions ----------------------------------------------------
@router.get("/sources")
def list_sources(request: Request, account: dict = Depends(_account)):  # noqa: B008
    """List my Instagram source subscriptions."""
    return {"sources": sources.list_for_account(_supabase(request), account["id"])}


@router.post("/sources", status_code=201)
def subscribe_source(
    body: SourceBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Subscribe to an Instagram source. Idempotent."""
    try:
        row = sources.subscribe(_supabase(request), account["id"], body.handle)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"subscribed": row["handle"], "enabled": row["enabled"]}


@router.delete("/sources/{handle}")
def unsubscribe_source(
    handle: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Unsubscribe from an Instagram source (disables the subscription)."""
    sources.set_enabled(_supabase(request), account["id"], handle, False)
    return {"unsubscribed": handle.strip().lstrip("@").lower()}


# --- scan jobs ---------------------------------------------------------------
@router.post("/scans", status_code=202)
def create_scan(body: ScanBody, request: Request):
    """Enqueue a scan job for a source.

    The fetch box polls GET /ig-logger/scans/pending, fetches the source
    on Instagram locally, and POSTs the posts back to
    /ig-logger/scans/{job_id}/complete. Service key -> scope 'all'
    (every subscribed account); personal token -> caller's account only.
    """
    only_account_id = resolve_scan_scope(request)
    scope = "all" if only_account_id is None else only_account_id
    try:
        result = jobs.create_job(_supabase(request), body.source_handle, scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/scans/pending")
def scans_pending(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    source_handle: str | None = Query(default=None),
):
    """Oldest pending scan job, for the fetch-box poller."""
    job = jobs.oldest_pending(_supabase(request), source_handle)
    if not job:
        from fastapi import Response

        return Response(status_code=204)
    return job


@router.post("/scans/{job_id}/complete")
def scan_complete(
    job_id: str,
    body: ScanCompleteBody,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Complete a scan job with posts fetched by the fetch box.

    CC runs the ingest pipeline under the job's stored scope and source:
    'all' fans out to every account subscribed to the source, via CC's
    internal authority (the poller never holds the service key).
    """
    supabase = _supabase(request)
    job = jobs.get_job(supabase, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown scan job")
    if job.get("status") != "pending":
        raise HTTPException(status_code=409, detail="job is not pending")
    jobs.mark_running(supabase, job_id)
    posts = [p.model_dump() for p in body.posts]
    scope = job.get("scope")
    only_account_id = None if scope == "all" else scope
    try:
        digests = runner.run_ingest(
            supabase, posts, job.get("source_handle") or "", only_account_id
        )
    except Exception as e:  # noqa: BLE001 - recorded on the job, then reported
        jobs.mark_failed(supabase, job_id, str(e))
        raise HTTPException(status_code=502, detail=f"ingest failed: {e}")
    jobs.mark_done(supabase, job_id, digests)
    return {"job_id": job_id, "status": "done", "digests": digests}


@router.get("/scans/{job_id}")
def scan_status(
    job_id: str,
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
):
    """Scan job status. The digest is filtered to the caller's own account."""
    job = jobs.get_job(_supabase(request), job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown scan job")
    if not jobs.job_includes(job, account["id"]):
        raise HTTPException(status_code=403, detail="not your scan job")
    out: dict = {
        "job_id": job_id,
        "status": job.get("status"),
        "source_handle": job.get("source_handle"),
    }
    if job.get("digest") is not None:
        for d in job["digest"] or []:
            if d.get("account_id") == account["id"]:
                out["digest"] = d
                break
    if job.get("error"):
        out["error"] = job["error"]
    return out


@router.get("/digest")
def digest(
    request: Request,
    account: dict = Depends(_account),  # noqa: B008
    source_handle: str | None = Query(default=None),
):
    """My most recent completed scan digest (optionally for one source)."""
    job = jobs.latest_done_for_account(
        _supabase(request), account["id"], source_handle
    )
    if not job:
        raise HTTPException(status_code=404, detail="no scan yet")
    for d in job.get("digest") or []:
        if d.get("account_id") == account["id"]:
            return d
    raise HTTPException(status_code=404, detail="no scan yet")
