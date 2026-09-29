"""Platform-level account identity for ig_logger.

A platform account is the Cozy Commons user row (currently stored in
`beli_accounts`, the original identity table). This module resolves a
personal bearer token to an account WITHOUT touching any sink's
credentials — sinks decrypt their own secrets from the row.

Sink-specific identity (Beli login crypto, token minting, onboarding)
lives in each sink's own accounts module.
"""

from __future__ import annotations

import hashlib
import hmac


class AccountError(Exception):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_account_row_by_token(supabase, token: str) -> dict:
    """Resolve a personal bearer token to its platform account row.

    Returns {"id", "label", "watcher_opt_in"} — no sink credentials.
    Raises AccountError when the token is unknown. Uses a constant-time
    comparison on the hash.
    """
    if not token or not token.startswith("ccb_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = (
        supabase.table("beli_accounts")
        .select("id,label,token_hash,watcher_opt_in")
        .execute()
    )
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {
                "id": row["id"],
                "label": row.get("label"),
                "watcher_opt_in": bool(row.get("watcher_opt_in")),
            }
    raise AccountError("unknown token")
