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
import logging
import secrets

from cryptography.fernet import InvalidToken, MultiFernet

from credential_keys import credentials_fernet

from .partiful_client import PartifulClient, PartifulError, normalize_phone

logger = logging.getLogger(__name__)


class AccountError(Exception):
    pass


def _fernet() -> MultiFernet:
    return credentials_fernet("PARTIFUL_CREDENTIALS_KEY", AccountError)


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


def get_account_row_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to {"id", "label"} without decrypting anything.

    Raises AccountError when the token is unknown. Constant-time hash compare.
    """
    if not token or not token.startswith("ccp_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = supabase.table("partiful_accounts").select("id,label,token_hash").execute()
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {"id": row["id"], "label": row.get("label")}
    raise AccountError("unknown token")


def linked_account_summary(supabase, user_id: str) -> dict | None:
    """The non-secret summary of the account a Commons user linked, if any."""
    rows = (
        supabase.table("partiful_accounts")
        .select("id,label")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    return {"id": rows[0]["id"], "label": rows[0].get("label")} if rows else None


def get_account_by_owner(supabase, user_id: str) -> dict:
    """Resolve a Commons user's linked account (with decrypted Partiful creds).

    Raises AccountError when the user has not linked an account.
    """
    rows = (
        supabase.table("partiful_accounts")
        .select("id,label,refresh_token_enc,uid_enc")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        raise AccountError("no linked account")
    row = rows[0]
    return {
        "id": row["id"],
        "label": row.get("label"),
        "refresh_token": decrypt_secret(row["refresh_token_enc"]),
        "uid": decrypt_secret(row["uid_enc"]),
    }


def link_account_to_owner(supabase, token: str, user_id: str) -> tuple[str, dict]:
    """Link the account a personal token names to a Commons user, once.

    The token is only hashed and compared; it is never stored. Only
    owner_user_id changes, so the stored refresh token is never touched.
    Returns (outcome, {"id", "label"}); outcome is linked | already_linked |
    other_owner. Raises AccountError when the token is unknown.
    """
    row = get_account_row_by_token(supabase, token)
    outcome = supabase.rpc(
        "partiful_link_account", {"p_account_id": row["id"], "p_user_id": str(user_id)}
    ).execute().data
    if outcome == "missing":
        raise AccountError("unknown token")
    return outcome, row


def _account_for_uid(supabase, uid: str) -> dict | None:
    # uid is Fernet-encrypted with a random IV, so there is no column to match
    # on; decrypting every row is fine at the handful of accounts we hold. A row
    # that will not decrypt (a key mismatch) is skipped rather than blocking
    # every connect; at worst it leads to a duplicate row.
    rows = (
        supabase.table("partiful_accounts")
        .select("id,label,uid_enc,owner_user_id")
        .execute()
    ).data or []
    for row in rows:
        try:
            stored = decrypt_secret(row["uid_enc"])
        except AccountError:
            logger.warning("Skipping Partiful account %s: its uid does not decrypt", row["id"])
            continue
        if stored and hmac.compare_digest(stored.encode(), uid.encode()):
            return row
    return None


def connect_account_for_owner(supabase, user_id: str, phone: str, code: str) -> tuple[str, dict]:
    """Link a Partiful account to a Commons user, proving ownership with an SMS code.

    This is the web replacement for presenting a ccp_ token. The code is
    verified live, which yields the account's Firebase uid; an existing account
    with that uid is reused (its stored session replaced by the fresh one), so a
    legacy user keeps their ccp_ token. Otherwise a new account is created with
    a token nobody ever sees. Returns (outcome, {"id", "label"}) where outcome
    is linked | already_linked | other_owner.
    Raises AccountError for invalid fields and PartifulError when Partiful
    refuses the code or does not answer.
    """
    try:
        phone = normalize_phone(phone)
    except PartifulError as e:
        raise AccountError(str(e))
    code = (code or "").strip()
    if not code:
        raise AccountError("SMS code is required")
    creds = PartifulClient.verify_auth_code(phone, code)

    row = _account_for_uid(supabase, creds["uid"])
    if row and row.get("owner_user_id") not in (None, str(user_id)):
        return "other_owner", {"id": row["id"], "label": row.get("label")}
    if row:
        account = {"id": row["id"], "label": row.get("label")}
    else:
        token = mint_token()  # the column is required; this token is never shown
        created = (supabase.table("partiful_accounts").insert({
            "label": "partiful",
            "refresh_token_enc": encrypt_secret(creds["refresh_token"]),
            "uid_enc": encrypt_secret(creds["uid"]),
            "token_hash": hash_token(token),
            "token_prefix": token[:12],
        }).execute().data or [{}])[0]
        if not created.get("id"):
            raise AccountError("could not create the Partiful account")
        account = {"id": created["id"], "label": "partiful"}
    outcome = supabase.rpc(
        "partiful_link_account", {"p_account_id": account["id"], "p_user_id": str(user_id)}
    ).execute().data
    if outcome not in ("linked", "already_linked", "other_owner"):
        raise AccountError("could not link the Partiful account")
    # Store the fresh session only once the row is the caller's, so a lost race
    # or a wrong match can never rewrite someone else's credentials.
    if row and outcome != "other_owner":
        supabase.table("partiful_accounts").update(
            {"refresh_token_enc": encrypt_secret(creds["refresh_token"])}
        ).eq("id", row["id"]).eq("owner_user_id", str(user_id)).execute()
    return outcome, account


def make_client_for_account(supabase, account: dict) -> PartifulClient:
    """Build the per-user client; rotated refresh tokens persist to the row."""

    def _persist(new_refresh_token: str) -> None:
        supabase.table("partiful_accounts").update(
            {"refresh_token_enc": encrypt_secret(new_refresh_token)}
        ).eq("id", account["id"]).execute()

    return PartifulClient(
        account["refresh_token"], account["uid"], on_refresh=_persist
    )
