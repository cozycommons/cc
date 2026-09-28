"""Partiful read logic: pure functions over a PartifulClient (no framework code).

Scopes:
  hosted  — events the user hosts (getPublishedEvents)
  rsvps   — getMyRsvps events the user actually responded to
  invited — every getMyRsvps event (any status, including unresponded invites)
  all     — hosted + invited, deduplicated by event id
"""

from __future__ import annotations

from datetime import datetime

# guest.status values that count as "the user responded"
RESPONDED_STATUSES = {
    "GOING",
    "MAYBE",
    "DECLINED",
    "INTERESTED",
    "PENDING_APPROVAL",
    "APPROVED",
    "WAITLIST",
    "WAITLISTED_FOR_APPROVAL",
    "WITHDRAWN",
    "REJECTED",
}

_SCOPES = ("all", "hosted", "rsvps", "invited")


def _slim_event(event: dict, scopes: set, rsvp_status: str | None) -> dict:
    return {
        "id": event.get("id"),
        "title": event.get("title"),
        "startDate": event.get("startDate"),
        "endDate": event.get("endDate"),
        "timezone": event.get("timezone"),
        "location": event.get("location") or event.get("locationDisplayText"),
        "status": event.get("status"),
        "rsvp_status": rsvp_status,
        "scopes": sorted(scopes),
        "attended_guest_count": event.get("attendedGuestCount"),
    }


def _parse_date(value: str, name: str):
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise ValueError(f"{name} must be YYYY-MM-DD")


def _event_date(event: dict):
    """The event's start as a date, or None when unknown ("TBD"/missing)."""
    raw = event.get("startDate")
    if not raw or raw == "TBD":
        return None
    try:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def list_events(client, scope: str = "all", start: str | None = None, end: str | None = None) -> dict:
    """List the caller's Partiful events, merged across scopes.

    start/end are YYYY-MM-DD bounds (inclusive) on the event start date.
    """
    scope = (scope or "all").lower()
    if scope not in _SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(_SCOPES)}")
    start_d = _parse_date(start, "start") if start else None
    end_d = _parse_date(end, "end") if end else None
    if start_d and end_d and start_d > end_d:
        raise ValueError("start must be on or before end")

    merged: dict[str, tuple[dict, set, str | None]] = {}

    def _add(event: dict, scopes, rsvp_status: str | None):
        eid = event.get("id")
        if not eid:
            return
        if isinstance(scopes, str):
            scopes = {scopes}
        if eid in merged:
            prev, pscopes, prsvp = merged[eid]
            merged[eid] = (prev, pscopes | set(scopes), prsvp or rsvp_status)
        else:
            merged[eid] = (event, set(scopes), rsvp_status)

    if scope in ("all", "hosted"):
        for event in client.get_published_events():
            if isinstance(event, dict):
                _add(event, "hosted", None)
    if scope in ("all", "rsvps", "invited"):
        for event in client.get_my_rsvps():
            if not isinstance(event, dict):
                continue
            status = (event.get("guest") or {}).get("status")
            scopes = {"invited"}
            if status in RESPONDED_STATUSES:
                scopes.add("rsvp")
            if scope == "rsvps" and "rsvp" not in scopes:
                continue
            _add(event, scopes, status)

    out = []
    for event, scopes, rsvp_status in merged.values():
        d = _event_date(event)
        if start_d and (d is None or d < start_d):
            continue
        if end_d and (d is None or d > end_d):
            continue
        out.append((_event_date(event), _slim_event(event, scopes, rsvp_status)))
    out.sort(key=lambda t: (t[0] is None, t[0]))
    return {"events": [slim for _, slim in out], "count": len(out)}


def get_event(client, event_id: str) -> dict:
    """Detail for one viewable event."""
    event_id = (event_id or "").strip()
    if not event_id:
        raise ValueError("event_id is required")
    info = client.get_event_info(event_id)
    event = info.get("event") if isinstance(info, dict) else None
    if not isinstance(event, dict):
        raise ValueError("event not found")
    return {
        "event": _slim_event(event, set(), None),
        "password_required": bool(info.get("passwordRequired")),
    }
