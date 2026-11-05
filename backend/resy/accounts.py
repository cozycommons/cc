"""Per-user Resy account storage.

Each friend onboards with their Resy email + password (through the secure
vault — never in chat). The backend logs into api.resy.com once, then stores
the email, password, and current auth token encrypted at rest with Fernet (key
from RESY_CREDENTIALS_KEY). Tokens and passwords never leave the server except
inside authenticated Resy API calls.

Trust note: a Resy password logs directly into resy.com as the user — the
biggest trust ask of the Cozy Commons integrations so far. The backend holds
it; agents only ever receive a scoped ``ccr_...`` bearer token.

API access is per-account: onboarding mints a personal bearer token
("ccr_..."), shown once. The token's sha256 hash is stored; the plaintext is
never persisted. Every /resy request resolves the token to exactly one
account, so one friend's token can never touch another friend's Resy data.

Refreshed auth tokens are persisted back to the account row (best-effort) so
a rotation never forces a re-onboard.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from cryptography.fernet import InvalidToken, MultiFernet

from credential_keys import credentials_fernet

from .resy_client import ResyClient, ResyAuthError, ResyError

logger = logging.getLogger(__name__)


class AccountError(Exception):
    pass


def _fernet() -> MultiFernet:
    return credentials_fernet("RESY_CREDENTIALS_KEY", AccountError)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise AccountError(
            "Could not decrypt stored credentials (RESY_CREDENTIALS_KEY mismatch?)"
        )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> str:
    return "ccr_" + secrets.token_urlsafe(32)


def create_account(supabase, label: str, email: str, password: str) -> dict:
    """Log into Resy live, then store the account.

    Returns {"id", "label", "token"} — the token plaintext is shown ONCE here
    and never again. Raises AccountError / ResyAuthError on failure.
    """
    label = (label or "").strip()[:80] or "resy"
    email = (email or "").strip()
    if not email or "@" not in email:
        raise AccountError("a valid email is required")
    if not password:
        raise AccountError("password is required")
    # verify against Resy before storing anything
    try:
        client = ResyClient.login_with(email, password)
    except ResyAuthError as e:
        raise AccountError(f"Resy login failed: {e}")
    except ResyError as e:
        raise AccountError(f"Resy login failed: {e}")

    token = mint_token()
    row = {
        "label": label,
        "email_enc": encrypt_secret(email),
        "password_enc": encrypt_secret(password),
        "auth_token_enc": encrypt_secret(client._auth_token or ""),
        "token_hash": hash_token(token),
        "token_prefix": token[:12],
    }
    res = supabase.table("resy_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    return {"id": created.get("id"), "label": label, "token": token}


def get_account_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to its account (with decrypted Resy creds).

    Raises AccountError when the token is unknown. Uses a constant-time
    comparison on the hash.
    """
    if not token or not token.startswith("ccr_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = (
        supabase.table("resy_accounts")
        .select("id,label,email_enc,password_enc,auth_token_enc,token_hash")
        .execute()
    )
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            auth_token = decrypt_secret(row["auth_token_enc"]) or None
            return {
                "id": row["id"],
                "label": row.get("label"),
                "email": decrypt_secret(row["email_enc"]),
                "password": decrypt_secret(row["password_enc"]),
                "auth_token": auth_token,
            }
    raise AccountError("unknown token")


def get_account_row_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to {"id", "label"} without decrypting anything.

    Raises AccountError when the token is unknown. Constant-time hash compare.
    """
    if not token or not token.startswith("ccr_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = supabase.table("resy_accounts").select("id,label,token_hash").execute()
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {"id": row["id"], "label": row.get("label")}
    raise AccountError("unknown token")


def linked_account_summary(supabase, user_id: str) -> dict | None:
    """The non-secret summary of the account a Commons user linked, if any."""
    rows = (
        supabase.table("resy_accounts")
        .select("id,label")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    return {"id": rows[0]["id"], "label": rows[0].get("label")} if rows else None


def get_account_by_owner(supabase, user_id: str) -> dict:
    """Resolve a Commons user's linked account (with decrypted Resy creds).

    Raises AccountError when the user has not linked an account.
    """
    rows = (
        supabase.table("resy_accounts")
        .select("id,label,email_enc,password_enc,auth_token_enc")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        raise AccountError("no linked account")
    row = rows[0]
    return {
        "id": row["id"],
        "label": row.get("label"),
        "email": decrypt_secret(row["email_enc"]),
        "password": decrypt_secret(row["password_enc"]),
        "auth_token": decrypt_secret(row["auth_token_enc"]) or None,
    }



def login_key(email: str) -> str:
    """One Resy login's canonical form: the email, ASCII-lowercased.

    Only ASCII is case-folded: str.lower() maps look-alikes such as the Kelvin
    sign to ASCII letters, which would let a different Resy login match.
    """
    value = email.strip()
    return value.lower() if value.isascii() else value


def _account_for_login(supabase, email: str) -> dict | None:
    # email is Fernet-encrypted with a random IV, so there is no column to match
    # on; decrypting every row is fine at the handful of accounts we hold. A row
    # that will not decrypt (a key mismatch) is skipped rather than blocking
    # every connect; at worst it leads to a duplicate row.
    rows = (
        supabase.table("resy_accounts")
        .select("id,label,email_enc,owner_user_id")
        .execute()
    ).data or []
    wanted = login_key(email)
    for row in rows:
        try:
            stored = decrypt_secret(row["email_enc"])
        except AccountError:
            logger.warning("Skipping Resy account %s: its login does not decrypt", row["id"])
            continue
        if login_key(stored) == wanted:
            return row
    return None


def connect_account_for_owner(supabase, user_id: str, email: str, password: str) -> tuple[str, dict]:
    """Link a Resy login to a Commons user, proving ownership with the login itself.

    This is the web replacement for presenting a ccr_ token. The login is
    checked live with Resy first. An existing account with the same email is
    reused (its stored password and session refreshed), so a legacy user keeps
    their receipts and their ccr_ token keeps working; otherwise a new account
    is created with a token nobody ever sees. Returns (outcome, {"id", "label"})
    where outcome is linked | already_linked | other_owner.
    Raises AccountError for missing fields and ResyAuthError / ResyError when
    Resy refuses or does not answer.
    """
    email = (email or "").strip()
    if not email or "@" not in email or not password:
        raise AccountError("email and password are required")
    if not email.isascii():
        raise AccountError("email must be ASCII")
    session = ResyClient.login_with(email, password)._auth_token or ""

    row = _account_for_login(supabase, email)
    if row and row.get("owner_user_id") not in (None, str(user_id)):
        return "other_owner", {"id": row["id"], "label": row.get("label")}
    if row:
        account = {"id": row["id"], "label": row.get("label")}
    else:
        token = mint_token()  # the column is required; this token is never shown
        created = (supabase.table("resy_accounts").insert({
            "label": "resy",
            "email_enc": encrypt_secret(email),
            "password_enc": encrypt_secret(password),
            "auth_token_enc": encrypt_secret(session),
            "token_hash": hash_token(token),
            "token_prefix": token[:12],
        }).execute().data or [{}])[0]
        if not created.get("id"):
            raise AccountError("could not create the Resy account")
        account = {"id": created["id"], "label": "resy"}
    outcome = supabase.rpc(
        "resy_link_account", {"p_account_id": account["id"], "p_user_id": str(user_id)}
    ).execute().data
    if outcome not in ("linked", "already_linked", "other_owner"):
        raise AccountError("could not link the Resy account")
    # Refresh the stored login only once the row is the caller's, so a lost race
    # or a wrong match can never rewrite someone else's credentials.
    if row and outcome != "other_owner":
        supabase.table("resy_accounts").update({
            "password_enc": encrypt_secret(password),
            "auth_token_enc": encrypt_secret(session),
        }).eq("id", row["id"]).eq("owner_user_id", str(user_id)).execute()
    return outcome, account


def make_client_for_account(supabase, account: dict) -> ResyClient:
    """Build the per-user client; refreshed tokens persist to the row."""

    def _persist(new_token: str) -> None:
        supabase.table("resy_accounts").update(
            {"auth_token_enc": encrypt_secret(new_token)}
        ).eq("id", account["id"]).execute()

    return ResyClient(
        auth_token=account.get("auth_token"),
        email=account["email"],
        password=account["password"],
        on_token_refresh=_persist,
    )
