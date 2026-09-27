"""@beli_eats -> Beli auto-bookmark watcher, per-user edition.

Post ingestion happens outside this service: a scheduled job on the
operator's harness pulls recent @beli_eats posts through the native
Instagram integration and POSTs them to /beli/eats-ingest. For every
account with watcher_opt_in=true this module then:

  1. extracts restaurant-name candidates from captions,
  2. bookmarks confident matches into THAT account's Beli via the shared
     confidence gate (ambiguous names are never written),
  3. advances the account's last_eats_scan watermark.

Each account keeps its own watermark, so friends onboard at different times
without missing or re-processing posts.
"""

from __future__ import annotations

from . import accounts
from .accounts import AccountError, make_client_for_account
from .logic import bookmark_name, candidates_from_caption, guess_city


def _norm_ts(ts: str) -> str:
    """Normalize a post timestamp for watermark string comparison.

    Accepts ISO-8601 ("2026-09-26T17:14:52+00:00") and the space-separated
    form some fetchers emit ("2026-09-26 17:14:52"). Mixed formats break
    the lexicographic watermark comparison, so normalize to the T form.
    """
    ts = (ts or "").strip()
    if len(ts) >= 19 and ts[10] == " ":
        ts = ts[:10] + "T" + ts[11:]
    return ts


def scan_account_for_posts(account: dict, posts: list) -> dict:
    """Run the watch pipeline for one account. Returns a digest dict.

    Never raises on per-name failures; they are reported as skipped.
    """
    last_ts = account.get("last_eats_scan") or ""
    new_posts = sorted(
        (p for p in posts if (p.get("created_at") or "") > last_ts),
        key=lambda p: p.get("created_at") or "",
    )
    digest = {
        "account": account.get("label"),
        "checked": len(new_posts),
        "bookmarked": [],
        "already": [],
        "skipped": [],
        "newest_ts": last_ts,
    }
    if not new_posts:
        return digest

    client = make_client_for_account(account)
    seen_names: set[str] = set()
    for p in new_posts:
        caption = p.get("post_caption") or ""
        city = guess_city(caption)
        for name in candidates_from_caption(caption):
            key = name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            try:
                data = bookmark_name(client, name, city)
            except Exception as e:  # noqa: BLE001 - per-name failures are digest noise
                digest["skipped"].append(f"{name} [error: {e}]")
                continue
            st = data.get("status")
            if st == "bookmarked":
                b = data.get("business") or {}
                label = b.get("name") or name
                if b.get("neighborhood"):
                    label += f" ({b['neighborhood']})"
                digest["bookmarked"].append(label)
            elif st in ("already_bookmarked", "already_ranked"):
                digest["already"].append(name)
            else:
                digest["skipped"].append(name)

    digest["newest_ts"] = max(p.get("created_at") or "" for p in new_posts)
    return digest


def format_digest(digest: dict) -> str:
    lines = [
        f"Beli Eats watch ({digest['account']}): checked {digest['checked']} new post(s)."
    ]
    if digest["bookmarked"]:
        lines.append("Bookmarked: " + "; ".join(digest["bookmarked"]))
    if digest["already"]:
        lines.append(
            f"Already saved ({len(digest['already'])}): " + "; ".join(digest["already"][:8])
        )
    if digest["skipped"]:
        lines.append(
            f"Skipped as ambiguous ({len(digest['skipped'])}): "
            + "; ".join(digest["skipped"][:8])
        )
    if not (digest["bookmarked"] or digest["already"] or digest["skipped"]):
        lines.append("No restaurant names extracted.")
    return "\n".join(lines)


def run_eats_ingest(
    posts: list, supabase, only_account_id: str | None = None
) -> list[dict]:
    """Run the watch pipeline for every opted-in account.

    `posts` are dicts with at least `created_at` and `post_caption`.
    When `only_account_id` is given, only that account is processed
    (used when the caller authenticated with a personal API token
    instead of the harness service key).
    Returns one digest dict per account. Never raises on per-account
    failures; they are reported in the digest as skipped.
    """
    posts = [
        {**p, "created_at": _norm_ts(p.get("created_at") or "")} for p in posts
    ]
    query = (
        supabase.table("beli_accounts")
        .select("id,label,beli_id_enc,password_enc,token_hash,watcher_opt_in,last_eats_scan")
        .eq("watcher_opt_in", True)
    )
    if only_account_id:
        query = query.eq("id", only_account_id)
    res = query.execute()
    rows = res.data or []
    digests = []
    for row in rows:
        label = row.get("label")
        try:
            account = {
                "id": row["id"],
                "label": label,
                "beli_id": accounts.decrypt_secret(row["beli_id_enc"]),
                "password": accounts.decrypt_secret(row["password_enc"]),
            }
        except AccountError as e:
            digests.append(
                {
                    "account": label,
                    "checked": 0,
                    "bookmarked": [],
                    "already": [],
                    "skipped": [f"account error: {e}"],
                    "newest_ts": row.get("last_eats_scan") or "",
                }
            )
            continue
        digest = scan_account_for_posts(
            {**account, "last_eats_scan": row.get("last_eats_scan")}, posts
        )
        if digest["newest_ts"]:
            supabase.table("beli_accounts").update(
                {"last_eats_scan": digest["newest_ts"]}
            ).eq("id", row["id"]).execute()
        digests.append(digest)
    return digests
