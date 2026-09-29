"""Scan-job queue for the poll-model fetch box.

One row per scan: which Instagram source to fetch (`source_handle`) and
whose data to update (`scope`: 'all' = every account subscribed to the
source, or a single account id). Insert row = publish, poll pending =
consume, mark done = acknowledge.

The fetch box never holds the ingest key: a job's scope is fixed at
creation time by whoever was authorized to create it, and completing a
job just delivers posts — it cannot change the scope.
"""

from __future__ import annotations

TABLE = "ig_scan_jobs"
STATUSES = ("pending", "running", "done", "failed")


def create_job(supabase, source_handle: str, scope: str) -> dict:
    source_handle = (source_handle or "").strip().lstrip("@").lower()
    if not source_handle:
        raise ValueError("source_handle is required")
    res = (
        supabase.table(TABLE)
        .insert({"source_handle": source_handle, "scope": scope, "status": "pending"})
        .execute()
    )
    row = (res.data or [{}])[0]
    return {"job_id": row.get("id"), "status": "queued"}


def oldest_pending(supabase, source_handle: str | None = None) -> dict | None:
    """Oldest pending job, optionally filtered to one source.

    Only reveals work-to-do (job id, source, scope), never user data.
    """
    query = (
        supabase.table(TABLE)
        .select("id,source_handle,scope")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
    )
    if source_handle:
        query = query.eq(
            "source_handle", source_handle.strip().lstrip("@").lower()
        )
    rows = (query.execute().data) or []
    if not rows:
        return None
    return {
        "job_id": rows[0]["id"],
        "source_handle": rows[0]["source_handle"],
        "scope": rows[0]["scope"],
    }


def get_job(supabase, job_id: str) -> dict | None:
    res = supabase.table(TABLE).select("*").eq("id", job_id).execute()
    rows = res.data or []
    return rows[0] if rows else None


def mark_running(supabase, job_id: str) -> None:
    supabase.table(TABLE).update({"status": "running"}).eq("id", job_id).execute()


def mark_done(supabase, job_id: str, digest: list) -> None:
    supabase.table(TABLE).update({"status": "done", "digest": digest}).eq(
        "id", job_id
    ).execute()


def mark_failed(supabase, job_id: str, error: str) -> None:
    supabase.table(TABLE).update(
        {"status": "failed", "error": (error or "")[:500]}
    ).eq("id", job_id).execute()


def latest_done_for_account(
    supabase, account_id: str, source_handle: str | None = None
) -> dict | None:
    """Most recent completed job whose scope includes this account."""
    query = (
        supabase.table(TABLE)
        .select("scope,digest,source_handle")
        .eq("status", "done")
        .order("created_at", desc=True)
    )
    if source_handle:
        query = query.eq(
            "source_handle", source_handle.strip().lstrip("@").lower()
        )
    for job in (query.execute().data or []):
        if job.get("scope") in ("all", account_id):
            return job
    return None


def job_includes(job: dict, account_id: str) -> bool:
    return job.get("scope") in ("all", account_id)
