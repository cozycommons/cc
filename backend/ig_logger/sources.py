"""Per-user Instagram source subscriptions.

A source is a public Instagram account (by handle) whose posts a user
wants pulled into the platform. Each subscription carries its own
watermark (`last_seen_ts`), so accounts onboarded at different times
never miss or re-process posts from a source.

The Beli app subscribes every onboarded account to 'beli_eats' by
default; the watcher opt-in toggle keeps the subscription in sync.
"""

from __future__ import annotations

TABLE = "ig_sources"


def subscribe(supabase, account_id: str, handle: str, enabled: bool = True) -> dict:
    """Subscribe an account to a source (idempotent upsert)."""
    handle = (handle or "").strip().lstrip("@").lower()
    if not handle:
        raise ValueError("handle is required")
    row = {
        "account_id": account_id,
        "handle": handle,
        "enabled": bool(enabled),
    }
    res = (
        supabase.table(TABLE)
        .upsert(row, on_conflict="account_id,handle")
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else row


def list_for_account(supabase, account_id: str) -> list[dict]:
    res = (
        supabase.table(TABLE)
        .select("handle,enabled,last_seen_ts,created_at")
        .eq("account_id", account_id)
        .order("handle")
        .execute()
    )
    return res.data or []


def set_enabled(supabase, account_id: str, handle: str, enabled: bool) -> None:
    handle = (handle or "").strip().lstrip("@").lower()
    supabase.table(TABLE).update({"enabled": bool(enabled)}).eq(
        "account_id", account_id
    ).eq("handle", handle).execute()


def subscribed_account_ids(supabase, handle: str) -> list[str]:
    """Every account with an enabled subscription to this source."""
    handle = (handle or "").strip().lstrip("@").lower()
    res = (
        supabase.table(TABLE)
        .select("account_id")
        .eq("handle", handle)
        .eq("enabled", True)
        .execute()
    )
    return [r["account_id"] for r in (res.data or [])]


def is_subscribed(supabase, account_id: str, handle: str) -> bool:
    handle = (handle or "").strip().lstrip("@").lower()
    res = (
        supabase.table(TABLE)
        .select("account_id")
        .eq("account_id", account_id)
        .eq("handle", handle)
        .eq("enabled", True)
        .execute()
    )
    return bool(res.data)


def get_watermark(supabase, account_id: str, handle: str) -> str:
    handle = (handle or "").strip().lstrip("@").lower()
    res = (
        supabase.table(TABLE)
        .select("last_seen_ts")
        .eq("account_id", account_id)
        .eq("handle", handle)
        .execute()
    )
    rows = res.data or []
    return (rows[0].get("last_seen_ts") if rows else "") or ""


def advance_watermark(supabase, account_id: str, handle: str, ts: str) -> None:
    if not ts:
        return
    handle = (handle or "").strip().lstrip("@").lower()
    supabase.table(TABLE).update({"last_seen_ts": ts}).eq(
        "account_id", account_id
    ).eq("handle", handle).execute()
