from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()
_process_start = perf_counter()

# Freshness thresholds for the tickr data health endpoint.
_EVENT_FRESHNESS_HOURS = 24
_LISTING_FRESHNESS_MINUTES = 120


def _get_latest_event_created_at(supabase) -> Optional[datetime]:
    try:
        response = (
            supabase.table("tickets_events")
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data:
            return None
        created_at = data[0].get("created_at")
        if not created_at:
            return None
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except Exception:
        return None


def _get_latest_snapshot_captured_at(supabase) -> Optional[datetime]:
    try:
        response = (
            supabase.table("orderbook_snapshots")
            .select("captured_at")
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data:
            return None
        captured_at = data[0].get("captured_at")
        if not captured_at:
            return None
        return datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(perf_counter() - _process_start, 3),
    }


@router.get("/tickrhealth")
def tickr_health_check(request: Request):
    now = datetime.now(timezone.utc)
    body: Dict[str, Any] = {
        "status": "ok",
        "timestamp": now.isoformat(),
        "uptime_seconds": round(perf_counter() - _process_start, 3),
    }

    supabase = getattr(request.app.state, "supabase", None)
    if supabase is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                **body,
                "status": "unhealthy",
                "reason": "supabase_not_configured",
            },
        )

    latest_event_at = _get_latest_event_created_at(supabase)
    latest_listing_at = _get_latest_snapshot_captured_at(supabase)

    event_cutoff = now - timedelta(hours=_EVENT_FRESHNESS_HOURS)
    listing_cutoff = now - timedelta(minutes=_LISTING_FRESHNESS_MINUTES)

    event_fresh = latest_event_at is not None and latest_event_at >= event_cutoff
    listing_fresh = latest_listing_at is not None and latest_listing_at >= listing_cutoff

    body["latest_event_at"] = latest_event_at.isoformat() if latest_event_at else None
    body["latest_listing_at"] = latest_listing_at.isoformat() if latest_listing_at else None
    body["event_fresh"] = event_fresh
    body["listing_fresh"] = listing_fresh
    body["event_freshness_hours"] = _EVENT_FRESHNESS_HOURS
    body["listing_freshness_minutes"] = _LISTING_FRESHNESS_MINUTES

    if not event_fresh or not listing_fresh:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                **body,
                "status": "unhealthy",
                "reason": "tickr_data_stale",
            },
        )

    return body
