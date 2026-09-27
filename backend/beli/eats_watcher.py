"""@beli_eats -> Beli auto-bookmark watcher, per-user edition.

For every account with watcher_opt_in=true:
  1. pull recent @beli_eats Instagram posts (best-effort; needs instaloader
     and, on most hosting IPs, an IG session via BELI_EATS_IG_USERNAME /
     BELI_EATS_IG_PASSWORD),
  2. extract restaurant-name candidates from captions,
  3. bookmark confident matches into THAT account's Beli via the shared
     confidence gate (ambiguous names are never written),
  4. advance the account's last_eats_scan watermark and print a digest.

Each account keeps its own watermark, so friends onboard at different times
without missing or re-processing posts.
"""

from __future__ import annotations

import os

from .accounts import make_client_for_account
from .logic import bookmark_name, candidates_from_caption, guess_city

IG_HANDLE = "beli_eats"


class BeliEatsUnavailable(Exception):
    pass


def fetch_beli_eats_posts(limit: int = 25) -> list:
    """Pull recent @beli_eats posts. Raises BeliEatsUnavailable when IG is unreachable."""
    try:
        import instaloader
    except ImportError:
        raise BeliEatsUnavailable("instaloader is not installed")
    try:
        loader = instaloader.Instaloader(
            quiet=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
        )
        ig_user = os.environ.get("BELI_EATS_IG_USERNAME")
        ig_pass = os.environ.get("BELI_EATS_IG_PASSWORD")
        if ig_user and ig_pass:
            loader.login(ig_user, ig_pass)
        profile = instaloader.Profile.from_username(loader.context, IG_HANDLE)
        posts = []
        for post in profile.get_posts():
            posts.append(
                {
                    "shortcode": post.shortcode,
                    "created_at": post.date_utc.isoformat(),
                    "post_caption": post.caption or "",
                }
            )
            if len(posts) >= limit:
                break
        return posts
    except Exception as e:
        raise BeliEatsUnavailable(f"could not fetch @{IG_HANDLE} posts: {e}")


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
