"""Shared data model for the ig_logger platform.

Posts arrive from fetch boxes as loose dicts (field names vary by fetcher),
so the platform normalizes them once here. Sinks receive normalized posts
and never have to care which fetcher produced them.
"""

from __future__ import annotations


def normalize_ts(ts: str | None) -> str:
    """Normalize a post timestamp for watermark string comparison.

    Accepts ISO-8601 ("2026-09-26T17:14:52+00:00") and the space-separated
    form some fetchers emit ("2026-09-26 17:14:52"). Mixed formats break
    the lexicographic watermark comparison, so normalize to the T form.
    """
    ts = (ts or "").strip()
    if len(ts) >= 19 and ts[10] == " ":
        ts = ts[:10] + "T" + ts[11:]
    return ts


def normalize_post(raw: dict) -> dict:
    """Normalize one raw fetched post into the platform post shape.

    Keeps every original key (sinks written against older fetchers keep
    working) and guarantees the canonical keys below.
    """
    raw = dict(raw or {})
    created_at = normalize_ts(raw.get("created_at"))
    caption = raw.get("post_caption") or raw.get("caption") or ""
    post = {
        **raw,
        "post_id": str(raw.get("post_id") or raw.get("id") or ""),
        "author": str(raw.get("author") or raw.get("post_author") or ""),
        "created_at": created_at,
        "post_caption": str(caption),
        "permalink": str(raw.get("permalink") or raw.get("post_url") or ""),
    }
    return post


def normalize_posts(raw_posts: list[dict]) -> list[dict]:
    return [normalize_post(p) for p in (raw_posts or [])]
