import logging
from typing import Any, Dict, Optional

import jwt as pyjwt
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_FIELD_LEN = 80
MAX_PATH_LEN = 200

router = APIRouter()

# Map of GET endpoint path -> (event_type, label) for lightweight traffic analytics,
# recorded automatically by the log_http_requests middleware in main.py whenever a
# tracked endpoint is hit. "search" entries pull their label from the named query
# param instead of a fixed label.
ANALYTICS_TRACKED_ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "/tickets/landing": {"app": "tickets", "event_type": "pageview", "label": "home"},
    "/tickets/event": {"app": "tickets", "event_type": "pageview", "label": "event_detail"},
    "/tickets/events_by_city": {"app": "tickets", "event_type": "pageview", "label": "city"},
    "/tickets/past_events": {"app": "tickets", "event_type": "pageview", "label": "past"},
    "/tickets/event_search": {"app": "tickets", "event_type": "search", "query_param": "search_for"},
}


def extract_auth_claims(request: Request) -> Dict[str, Optional[str]]:
    """Best-effort user id/email from a bearer token, without a network round trip.

    Decodes the JWT locally without verifying its signature -- fine for
    analytics (never used for authorization) and avoids an auth service call
    on every logged page view. Falls back to Nones for anonymous requests or
    malformed tokens.
    """
    empty = {"user_id": None, "email": None}
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return empty
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return empty
    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
        return {"user_id": claims.get("sub"), "email": claims.get("email")}
    except Exception:
        return empty


def resolve_client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def _insert_event(
    request: Request,
    app: str,
    event_type: str,
    label: Optional[str],
    path: str,
    client_ip: Optional[str],
) -> None:
    claims = extract_auth_claims(request)
    try:
        request.app.state.analytics_supabase.table("analytics_events").insert({
            "app": app,
            "event_type": event_type,
            "label": label,
            "path": path,
            "user_id": claims["user_id"],
            "email": claims["email"],
            "session_id": request.headers.get("x-session-id"),
            "ip_address": client_ip,
        }).execute()
    except Exception:
        logger.exception("Failed to record analytics event for %s", path)


def record_tracked_endpoint_event(
    request: Request, endpoint: str, status_code: int, client_ip: Optional[str]
) -> None:
    """Called from main.py's request-logging middleware for endpoints that imply
    a page view/search just by being fetched (e.g. the tickets landing data)."""
    if status_code >= 400:
        return
    spec = ANALYTICS_TRACKED_ENDPOINTS.get(endpoint)
    if not spec:
        return
    query_param = spec.get("query_param")
    label = request.query_params.get(query_param) if query_param else spec.get("label")
    if query_param and not label:
        return
    _insert_event(request, spec["app"], spec["event_type"], label, endpoint, client_ip)


class PageviewRequest(BaseModel):
    app: str = Field(..., min_length=1, max_length=MAX_FIELD_LEN)
    label: str = Field(..., min_length=1, max_length=MAX_FIELD_LEN)
    path: Optional[str] = Field(None, max_length=MAX_PATH_LEN)


@router.post("/pageview", status_code=204)
def track_pageview(payload: PageviewRequest, request: Request) -> None:
    """Public, best-effort pageview beacon for frontend routes that don't otherwise
    hit a tracked backend GET endpoint on load (e.g. static SPA landing pages)."""
    client_ip = resolve_client_ip(request)
    _insert_event(request, payload.app, "pageview", payload.label, payload.path or payload.app, client_ip)
