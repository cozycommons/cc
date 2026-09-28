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
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .resy_client import ResyClient, ResyAuthError, ResyError


class AccountError(Exception):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("RESY_CREDENTIALS_KEY", "")
    if not key:
        raise AccountError(
            "RESY_CREDENTIALS_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise AccountError(f"RESY_CREDENTIALS_KEY is invalid: {e}")


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
