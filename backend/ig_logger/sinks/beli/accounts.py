"""Per-user Beli account storage (Beli sink).

Each friend onboards with their own Beli login (email or phone + password).
Credentials are encrypted at rest with Fernet (key from BELI_CREDENTIALS_KEY)
and never leave the server except inside authenticated Beli API calls.

API access is per-account: onboarding mints a personal bearer token
("ccb_..."), shown once. The token's sha256 hash is stored; the plaintext is
never persisted. Every /beli request resolves the token to exactly one
account, so one friend's token can never touch another friend's Beli data.

Platform-level identity (token -> account row) lives in
`ig_logger/accounts.py`; this module adds the Beli-sink specifics.
"""

from __future__ import annotations

import secrets

from cryptography.fernet import InvalidToken, MultiFernet

from credential_keys import credentials_fernet

from ... import sources
from ...accounts import AccountError, get_account_row_by_token, hash_token
from .beli_client import BeliClient, BeliError

__all__ = [
    "AccountError",
    "encrypt_secret",
    "decrypt_secret",
    "hash_token",
    "create_account",
    "get_account_by_token",
    "get_account_by_owner",
    "linked_account_summary",
    "link_account_to_owner",
    "make_client_for_account",
]


def _fernet() -> MultiFernet:
    return credentials_fernet("BELI_CREDENTIALS_KEY", AccountError)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise AccountError(
            "Could not decrypt stored credentials (BELI_CREDENTIALS_KEY mismatch?)"
        )


def mint_token() -> str:
    return "ccb_" + secrets.token_urlsafe(32)


def create_account(supabase, label: str, beli_id: str, password: str) -> dict:
    """Validate Beli credentials live, then store the account.

    Returns {"id", "label", "token"} — the token plaintext is shown ONCE here
    and never again. Raises AccountError / BeliError on failure.
    """
    label = (label or "").strip()[:80] or "beli"
    beli_id = (beli_id or "").strip()
    if not beli_id or not password:
        raise AccountError("beli_id and password are required")
    # validate against Beli before storing anything
    try:
        BeliClient.probe_credentials(beli_id, password)
    except BeliError as e:
        raise AccountError(f"Beli login failed: {e}")

    token = mint_token()
    row = {
        "label": label,
        "beli_id_enc": encrypt_secret(beli_id),
        "password_enc": encrypt_secret(password),
        "token_hash": hash_token(token),
        "token_prefix": token[:12],
        # Watcher is on by default: onboarding once is enough to start
        # receiving @beli_eats bookmarks. POST /beli/watcher-opt-in toggles it.
        "watcher_opt_in": True,
    }
    res = supabase.table("beli_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    account_id = created.get("id")
    # Platform subscription: the Beli app watches @beli_eats for every account.
    if account_id:
        sources.subscribe(supabase, account_id, "beli_eats", enabled=True)
    return {"id": account_id, "label": label, "token": token}


def get_account_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to its account (with decrypted Beli creds).

    Raises AccountError when the token is unknown.
    """
    row = get_account_row_by_token(supabase, token)
    creds = (
        supabase.table("beli_accounts")
        .select("beli_id_enc,password_enc")
        .eq("id", row["id"])
        .execute()
    )
    cred_rows = creds.data or []
    if not cred_rows:
        raise AccountError("unknown token")
    return {
        "id": row["id"],
        "label": row.get("label"),
        "beli_id": decrypt_secret(cred_rows[0]["beli_id_enc"]),
        "password": decrypt_secret(cred_rows[0]["password_enc"]),
        "watcher_opt_in": bool(row.get("watcher_opt_in")),
    }


def linked_account_summary(supabase, user_id: str) -> dict | None:
    """The non-secret summary of the account a Commons user linked, if any."""
    rows = (
        supabase.table("beli_accounts")
        .select("id,label,watcher_opt_in")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        return None
    row = rows[0]
    return {"id": row["id"], "label": row.get("label"),
            "watcher_opt_in": bool(row.get("watcher_opt_in"))}


def get_account_by_owner(supabase, user_id: str) -> dict:
    """Resolve a Commons user's linked account (with decrypted Beli creds).

    Raises AccountError when the user has not linked an account.
    """
    rows = (
        supabase.table("beli_accounts")
        .select("id,label,watcher_opt_in,beli_id_enc,password_enc")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        raise AccountError("no linked account")
    row = rows[0]
    return {
        "id": row["id"],
        "label": row.get("label"),
        "beli_id": decrypt_secret(row["beli_id_enc"]),
        "password": decrypt_secret(row["password_enc"]),
        "watcher_opt_in": bool(row.get("watcher_opt_in")),
    }


def link_account_to_owner(supabase, token: str, user_id: str) -> tuple[str, dict]:
    """Link the account a personal token names to a Commons user, once.

    The token is only hashed and compared (constant time); it is never stored.
    Returns (outcome, account summary); outcome is linked | already_linked |
    other_owner. Watcher subscriptions are not touched.
    Raises AccountError when the token is unknown.
    """
    row = get_account_row_by_token(supabase, token)
    outcome = supabase.rpc(
        "beli_link_account", {"p_account_id": row["id"], "p_user_id": str(user_id)}
    ).execute().data
    if outcome == "missing":
        raise AccountError("unknown token")
    return outcome, {"id": row["id"], "label": row.get("label"),
                     "watcher_opt_in": row["watcher_opt_in"]}


def make_client_for_account(account: dict) -> BeliClient:
    return BeliClient(account["beli_id"], account["password"])
