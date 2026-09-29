"""Beli sink: the first ig_logger application.

Watches subscribed Instagram sources for restaurant mentions and
bookmarks confident matches into each enabled account's Beli "Want to
Try" via the shared confidence gate (ambiguous names are never
written). Implements the Sink protocol; registered with the platform
on import.
"""

from __future__ import annotations

from . import accounts
from .accounts import AccountError, make_client_for_account
from .logic import bookmark_name, candidates_from_caption, guess_city
from .. import register_sink


class BeliSink:
    name = "beli"

    def enabled_for(self, account: dict) -> bool:
        return bool(account.get("watcher_opt_in"))

    def process(self, posts: list[dict], account: dict) -> dict:
        """Run the Beli watch pipeline for one account.

        `posts` are normalized and already filtered to what's new for
        this account's subscription. `account` is the raw account row
        (Beli credentials decrypted here, inside the sink).
        Never raises on per-name failures; they are reported as skipped.
        """
        label = account.get("label")
        try:
            client = make_client_for_account(
                {
                    "beli_id": accounts.decrypt_secret(account["beli_id_enc"]),
                    "password": accounts.decrypt_secret(account["password_enc"]),
                }
            )
        except (AccountError, KeyError) as e:
            return {
                "account": label,
                "checked": len(posts),
                "bookmarked": [],
                "already": [],
                "skipped": [f"account error: {e}"],
                "newest_ts": "",
            }

        digest = {
            "account": label,
            "checked": len(posts),
            "bookmarked": [],
            "already": [],
            "skipped": [],
            "newest_ts": max((p.get("created_at") or "") for p in posts)
            if posts
            else "",
        }
        seen_names: set[str] = set()
        for p in posts:
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
                    item = b.get("name") or name
                    if b.get("neighborhood"):
                        item += f" ({b['neighborhood']})"
                    digest["bookmarked"].append(item)
                elif st in ("already_bookmarked", "already_ranked"):
                    digest["already"].append(name)
                else:
                    digest["skipped"].append(name)
        return digest


def format_digest(digest: dict) -> str:
    """Human-readable one-account digest, for chat delivery."""
    lines = [
        f"Beli Eats watch ({digest['account']}): checked {digest['checked']} new post(s)."
    ]
    if digest["bookmarked"]:
        lines.append("Bookmarked: " + "; ".join(digest["bookmarked"]))
    if digest["already"]:
        lines.append(
            f"Already saved ({len(digest['already'])}): "
            + "; ".join(digest["already"][:8])
        )
    if digest["skipped"]:
        lines.append(
            f"Skipped as ambiguous ({len(digest['skipped'])}): "
            + "; ".join(digest["skipped"][:8])
        )
    if not (digest["bookmarked"] or digest["already"] or digest["skipped"]):
        lines.append("No restaurant names extracted.")
    return "\n".join(lines)


register_sink(BeliSink())
