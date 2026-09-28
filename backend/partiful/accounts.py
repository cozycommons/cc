"""Per-user Partiful account storage.

Each friend onboards with their own phone number via Firebase SMS OTP.
The Firebase refresh token (+ uid) is encrypted at rest with Fernet (key from
PARTIFUL_CREDENTIALS_KEY) and never leaves the server except inside
authenticated Partiful API calls.

API access is per-account: onboarding mints a personal bearer token
("ccp_..."), shown once. The token's sha256 hash is stored; the plaintext is
never persisted. Every /partiful request resolves the token to exactly one
account, so one friend's token can never touch another friend's Partiful data.

Rotated refresh tokens are persisted back to the account row (best-effort) so
a rotation never forces a re-onboard.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .partiful_client import PartifulClient, PartifulError, normalize_phone


class AccountError(Exception):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("PARTIFUL_CREDENTIALS_KEY", "")
    if not key:
        raise AccountError(
            "PARTIFUL_CREDENTIALS_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise AccountError(f"PARTIFUL_CREDENTIALS_KEY is invalid: {e}")


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise AccountError(
            "Could not decrypt stored credentials (PARTIFUL_CREDENTIALS_KEY mismatch?)"
        )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> str:
    return "ccp_" + secrets.token_urlsafe(32)


def create_account(supabase, label: str, phone: str, code: str) -> dict:
    """Verify the SMS code live, then store the account.

    Returns {"id", "label", "token"} — the token plaintext is shown ONCE here
    and never again. Raises AccountError / PartifulError on failure.
    """
    label = (label or "").strip()[:80] or "partiful"
    try:
        phone = normalize_phone(phone)
    except PartifulError as e:
        raise AccountError(str(e))
    code = (code or "").strip()
    if not code:
        raise AccountError("SMS code is required")
    # verify against Partiful before storing anything
    try:
        creds = PartifulClient.verify_auth_code(phone, code)
    except PartifulError as e:
        raise AccountError(f"Partiful verification failed: {e}")

    token = mint_token()
    row = {
        "label": label,
        "refresh_token_enc": encrypt_secret(creds["refresh_token"]),
        "uid_enc": encrypt_secret(creds["uid"]),
        "token_hash": hash_token(token),
        "token_prefix": token[:12],
    }
    res = supabase.table("partiful_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    return {"id": created.get("id"), "label": label, "token": token}


def get_account_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to its account (with decrypted Partiful creds).

    Raises AccountError when the token is unknown. Uses a constant-time
    comparison on the hash.
    """
    if not token or not token.startswith("ccp_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = (
        supabase.table("partiful_accounts")
        .select("id,label,refresh_token_enc,uid_enc,token_hash")
        .execute()
    )
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {
                "id": row["id"],
                "label": row.get("label"),
                "refresh_token": decrypt_secret(row["refresh_token_enc"]),
                "uid": decrypt_secret(row["uid_enc"]),
            }
    raise AccountError("unknown token")


def make_client_for_account(supabase, account: dict) -> PartifulClient:
    """Build the per-user client; rotated refresh tokens persist to the row."""

    def _persist(new_refresh_token: str) -> None:
        supabase.table("partiful_accounts").update(
            {"refresh_token_enc": encrypt_secret(new_refresh_token)}
        ).eq("id", account["id"]).execute()

    return PartifulClient(
        account["refresh_token"], account["uid"], on_refresh=_persist
    )
