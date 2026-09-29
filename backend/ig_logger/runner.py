"""Fan-out runner: posts in, per-account per-sink digests out.

For one completed scan job: normalize the posts, find every account the
job's scope covers, filter to what's new past each account's watermark
for the source, run every enabled sink, advance watermarks, and return
one digest per account.

Per-sink failures never abort the run — a sink that raises is recorded
as failed in that account's digest and the rest continue.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import jobs, sources
from .models import normalize_posts
from .sinks import SINKS

# Register built-in sinks. Each sink module calls register_sink() on import.
from .sinks.beli import sink as _beli_sink  # noqa: F401


def _load_account_rows(supabase, account_ids: list[str]) -> dict[str, dict]:
    if not account_ids:
        return {}
    res = (
        supabase.table("beli_accounts")
        .select("id,label,beli_id_enc,password_enc,token_hash,watcher_opt_in")
        .in_("id", account_ids)
        .execute()
    )
    return {r["id"]: r for r in (res.data or [])}


def run_ingest(
    supabase,
    posts: list[dict],
    source_handle: str,
    only_account_id: str | None = None,
) -> list[dict]:
    """Run the ingest pipeline for one source.

    `only_account_id` scopes the run to a single account (personal-token
    callers); None fans out to every account subscribed to the source.
    Returns one digest dict per account.
    """
    posts = normalize_posts(posts)
    source_handle = (source_handle or "").strip().lstrip("@").lower()

    if only_account_id:
        candidate_ids = (
            [only_account_id]
            if sources.is_subscribed(supabase, only_account_id, source_handle)
            else []
        )
    else:
        candidate_ids = sources.subscribed_account_ids(supabase, source_handle)

    account_rows = _load_account_rows(supabase, candidate_ids)
    scanned_at = datetime.now(timezone.utc).isoformat()
    digests: list[dict] = []

    for account_id in candidate_ids:
        row = account_rows.get(account_id)
        if not row:
            continue
        watermark = sources.get_watermark(supabase, account_id, source_handle)
        new_posts = sorted(
            (p for p in posts if (p.get("created_at") or "") > watermark),
            key=lambda p: p.get("created_at") or "",
        )
        newest_ts = (
            max(p.get("created_at") or "" for p in new_posts) if new_posts else watermark
        )
        sink_digests: dict[str, dict] = {}
        if new_posts:
            for sink_name, sink in SINKS.items():
                if not sink.enabled_for(row):
                    continue
                try:
                    sink_digests[sink_name] = sink.process(new_posts, row)
                except Exception as e:  # noqa: BLE001 - one sink never kills the run
                    sink_digests[sink_name] = {
                        "account": row.get("label"),
                        "checked": len(new_posts),
                        "error": f"sink failed: {e}",
                    }
            # Advance the subscription watermark only when a sink actually
            # processed something: a fully-disabled run leaves the backlog so
            # re-enabling replays it, matching the legacy watcher semantics.
            if sink_digests and newest_ts:
                sources.advance_watermark(
                    supabase, account_id, source_handle, newest_ts
                )
        digests.append(
            {
                "account": row.get("label"),
                "account_id": account_id,
                "source": source_handle,
                "checked": len(new_posts),
                "sinks": sink_digests,
                "newest_ts": newest_ts,
                "scanned_at": scanned_at,
            }
        )
    return digests
