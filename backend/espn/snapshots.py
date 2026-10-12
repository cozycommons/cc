"""League snapshot storage for ESPN Fantasy trend queries.

A snapshot is one point-in-time league payload (built by
``logic.build_snapshot``); storing them gives trend queries — ownership
movement, player performance, team form — a time series to diff against
instead of only ever seeing the present.

Capture is capture-on-read in v1: ``ensure_snapshot`` returns the newest
stored snapshot when it is fresh enough, and otherwise builds, stores, and
returns a new one (reporting the previous snapshot alongside it so callers
can compute deltas). Snapshots are append-only history; a scheduled job may
reuse ``record_snapshot`` later without changing this storage layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import logic

CAPTURE_MIN_INTERVAL_S = 3600


def _parse_captured_at(value) -> datetime:
    """Parse a supabase ``captured_at`` value defensively.

    Values come back as ISO strings that may end in "Z" or carry an offset;
    naive values are treated as UTC.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def latest_snapshots(supabase, account_id, limit=2) -> list[dict]:
    """Newest stored snapshots for an account, newest first."""
    res = (
        supabase.table("espn_snapshots")
        .select("captured_at,payload")
        .eq("account_id", account_id)
        .order("captured_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        {"captured_at": row.get("captured_at"), "payload": row.get("payload")}
        for row in res.data or []
    ]


def record_snapshot(supabase, account_id, league_id, season, payload) -> None:
    """Append one snapshot row (``captured_at`` defaults to now() in SQL)."""
    supabase.table("espn_snapshots").insert(
        {
            "account_id": account_id,
            "league_id": league_id,
            "season": season,
            "payload": payload,
        }
    ).execute()


def ensure_snapshot(supabase, account, client, max_age_s=CAPTURE_MIN_INTERVAL_S) -> dict:
    """Return a fresh-enough snapshot, capturing a new one when stale.

    Returns {"current", "previous", "captured_at", "fresh_capture"}:
    ``previous`` is the snapshot before ``current`` (the older stored row
    when reusing, the just-superseded newest row when capturing), or None
    when there is no earlier snapshot.
    """
    rows = latest_snapshots(supabase, account["id"], limit=2)
    now = datetime.now(timezone.utc)
    if rows:
        try:
            age_s = (now - _parse_captured_at(rows[0]["captured_at"])).total_seconds()
        except (TypeError, ValueError):
            age_s = None
        if age_s is not None and age_s < max_age_s:
            return {
                "current": rows[0]["payload"],
                "previous": rows[1]["payload"] if len(rows) > 1 else None,
                "captured_at": rows[0]["captured_at"],
                "fresh_capture": False,
            }
    payload = logic.build_snapshot(client)
    record_snapshot(
        supabase, account["id"], account["league_id"], account["season"], payload
    )
    return {
        "current": payload,
        "previous": rows[0]["payload"] if rows else None,
        "captured_at": now.isoformat(),
        "fresh_capture": True,
    }
