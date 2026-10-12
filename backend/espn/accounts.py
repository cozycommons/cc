"""Per-user ESPN Fantasy account storage.

Each friend onboards with their own ESPN cookies (espn_s2 + SWID) for a
single basketball league — one account is exactly one league, with no
multi-league machinery. The cookies are encrypted at rest with Fernet (key
from ESPN_CREDENTIALS_KEY) and never leave the server except inside
authenticated ESPN API calls.

API access is per-account: onboarding mints a personal bearer token
("cce_..."), shown once. The token's sha256 hash is stored; the plaintext is
never persisted. Every /espn request resolves the token to exactly one
account, so one friend's token can never touch another friend's ESPN data.

ESPN cookies do not rotate (there is no refresh flow), so nothing is ever
persisted back to the account row after onboarding: when the cookies expire,
the user re-onboards with fresh ones.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .espn_client import EspnAuthError, EspnClient, EspnError


class AccountError(Exception):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("ESPN_CREDENTIALS_KEY", "")
    if not key:
        raise AccountError(
            "ESPN_CREDENTIALS_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise AccountError(f"ESPN_CREDENTIALS_KEY is invalid: {e}")


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise AccountError(
            "Could not decrypt stored credentials (ESPN_CREDENTIALS_KEY mismatch?)"
        )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> str:
    return "cce_" + secrets.token_urlsafe(32)


def _coerce_int(value, field: str) -> int:
    """Accept an int or a digit string; anything else is an AccountError."""
    if isinstance(value, bool):
        raise AccountError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise AccountError(f"{field} must be an integer")


def create_account(supabase, label, league_id, season, espn_s2, swid) -> dict:
    """Probe the ESPN cookies live, then store the account.

    Returns {"id", "label", "league_id", "season", "token"} — the token
    plaintext is shown ONCE here and never again. Raises AccountError on
    failure; nothing is stored when the probe fails.

    ``season`` is the ending year: the 2026-27 season is season 2027.
    """
    label = (label or "").strip()[:80] or "espn"
    league_id = _coerce_int(league_id, "league_id")
    if league_id <= 0:
        raise AccountError("league_id must be a positive integer")
    season = _coerce_int(season, "season")
    if not 2019 <= season <= 2100:
        raise AccountError("season must be between 2019 and 2100")
    espn_s2 = (espn_s2 or "").strip()
    swid = (swid or "").strip()
    if not espn_s2:
        raise AccountError("espn_s2 cookie is required")
    if not swid:
        raise AccountError("SWID cookie is required")
    # verify against ESPN before storing anything
    try:
        EspnClient.probe(espn_s2, swid, league_id, season)
    except EspnAuthError:
        raise AccountError(
            "ESPN cookies were rejected (expired?); grab fresh "
            "espn_s2/SWID cookies and re-onboard"
        )
    except EspnError as e:
        raise AccountError(f"ESPN verification failed: {e}")

    token = mint_token()
    row = {
        "label": label,
        "league_id": league_id,
        "season": season,
        "espn_s2_enc": encrypt_secret(espn_s2),
        "swid_enc": encrypt_secret(swid),
        "token_hash": hash_token(token),
        "token_prefix": token[:12],
    }
    res = supabase.table("espn_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    return {
        "id": created.get("id"),
        "label": label,
        "league_id": league_id,
        "season": season,
        "token": token,
    }


def get_account_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to its account (with decrypted ESPN cookies).

    Raises AccountError when the token is unknown. Uses a constant-time
    comparison on the hash.
    """
    if not token or not token.startswith("cce_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = (
        supabase.table("espn_accounts")
        .select("id,label,league_id,season,espn_s2_enc,swid_enc,token_hash")
        .execute()
    )
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {
                "id": row["id"],
                "label": row.get("label"),
                "league_id": row.get("league_id"),
                "season": row.get("season"),
                "espn_s2": decrypt_secret(row["espn_s2_enc"]),
                "swid": decrypt_secret(row["swid_enc"]),
            }
    raise AccountError("unknown token")


def make_client_for_account(account: dict) -> EspnClient:
    """Build the per-user client from a resolved account dict."""
    return EspnClient(
        account["espn_s2"], account["swid"], account["league_id"], account["season"]
    )
