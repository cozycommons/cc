"""Per-user Maple telemetry accounts.

One account is one person's telemetry stream. Access is a personal bearer
token ("ccm_..."), minted at onboarding and shown once; only its sha256
hash is stored, never the plaintext. Unlike ESPN/Beli/Resy there are no
third-party credentials here — the token is the only secret, so nothing is
encrypted at rest in this module.

Every request resolves the token to exactly one account, and every
telemetry row carries that account's id as user_id, so one person's token
can never read or write another person's rows.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


class AccountError(Exception):
    pass


def hash_token(token: str) -> str:
    # The token is a 256-bit random bearer token (secrets.token_urlsafe),
    # not a human password: a fast hash is the correct storage here, the
    # same pattern as espn/beli accounts. Password KDFs defend low-entropy
    # secrets against guessing; there is nothing to guess at 256 bits.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()  # codeql[py/weak-sensitive-data-hashing]


def mint_token() -> str:
    return "ccm_" + secrets.token_urlsafe(32)


def create_account(supabase, label=None) -> dict:
    """Mint a telemetry account and its personal token.

    Returns {"id", "label", "token"} — the token plaintext is shown ONCE
    here and never again.
    """
    label = (label or "").strip()[:80] or "maple"
    token = mint_token()
    row = {
        "label": label,
        "token_hash": hash_token(token),
        "token_prefix": token[:12],
    }
    res = supabase.table("maple_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    if not created.get("id"):
        raise AccountError("could not create the telemetry account")
    return {"id": created["id"], "label": label, "token": token}


def get_account_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to {"id", "label"}.

    Raises AccountError when the token is unknown. Uses a constant-time
    comparison on the hash. Callers must pass an uncached Supabase client:
    a retired token has to stop working on the next request
    (docs/security.md).
    """
    if not token or not token.startswith("ccm_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = supabase.table("maple_accounts").select("id,label,token_hash").execute()
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {"id": row["id"], "label": row.get("label")}
    raise AccountError("unknown token")


def delete_account(supabase, account_id) -> str:
    """Delete one account row (self-service disconnect).

    The caller's token resolved to this account, so an account can only
    ever delete itself. maple_exp_runs declares
    ``user_id ... references maple_accounts(id) on delete cascade``
    (migration 0094), so the account's telemetry goes with it. Once the
    row is gone the token hash is gone too, so the token resolves to
    nothing and every later request with it is a 401.
    """
    supabase.table("maple_accounts").delete().eq("id", account_id).execute()
    return account_id
