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
import logging
import secrets

from cryptography.fernet import InvalidToken, MultiFernet

from credential_keys import credentials_fernet

from .espn_client import EspnAuthError, EspnClient, EspnError, RequestCooldown

logger = logging.getLogger(__name__)


class AccountError(Exception):
    pass


def _fernet() -> MultiFernet:
    return credentials_fernet("ESPN_CREDENTIALS_KEY", AccountError)


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


def create_account(
    supabase, label, league_id, season, espn_s2, swid, *, enable_automation=True
) -> dict:
    """Probe the ESPN cookies live, then store the account.

    Returns {"id", "label", "league_id", "season", "token"} — the token
    plaintext is shown ONCE here and never again. Raises AccountError on
    failure; nothing is stored when the probe fails.

    ``season`` is the ending year: the 2026-27 season is season 2027.

    Store the automation choice in the initial insert, so an opt-out
    never becomes temporarily eligible for the scheduler. Legacy callers
    that omit the choice retain the enabled default.
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
        "lineup_automation_enabled": bool(enable_automation),
    }
    res = supabase.table("espn_accounts").insert(row).execute()
    created = (res.data or [{}])[0]
    return {
        "id": created.get("id"),
        "label": label,
        "league_id": league_id,
        "season": season,
        "token": token,
        "lineup_automation_enabled": bool(enable_automation),
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
        .select(
            "id,label,league_id,season,espn_s2_enc,swid_enc,token_hash,"
            "lineup_automation_enabled"
        )
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
                "lineup_automation_enabled": bool(
                    row.get("lineup_automation_enabled")
                ),
            }
    raise AccountError("unknown token")


def get_account_row_by_token(supabase, token: str) -> dict:
    """Resolve a bearer token to {"id", "label"} without decrypting anything.

    Raises AccountError when the token is unknown. Constant-time hash compare.
    """
    if not token or not token.startswith("cce_"):
        raise AccountError("invalid token")
    wanted = hash_token(token)
    res = supabase.table("espn_accounts").select("id,label,token_hash").execute()
    for row in res.data or []:
        if hmac.compare_digest(str(row.get("token_hash") or ""), wanted):
            return {"id": row["id"], "label": row.get("label")}
    raise AccountError("unknown token")


def linked_account_summary(supabase, user_id: str) -> dict | None:
    """The non-secret summary of the account a Commons user linked, if any."""
    rows = (
        supabase.table("espn_accounts")
        .select("id,label,league_id,season")
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        return None
    row = rows[0]
    return {"id": row["id"], "label": row.get("label"),
            "league_id": row.get("league_id"), "season": row.get("season")}


def get_account_by_owner(supabase, user_id: str) -> dict:
    """Resolve a Commons user's linked account (with decrypted ESPN cookies).

    Returns the same shape as :func:`get_account_by_token`. Raises
    AccountError when the user has not linked an account.
    """
    rows = (
        supabase.table("espn_accounts")
        .select(
            "id,label,league_id,season,espn_s2_enc,swid_enc,"
            "lineup_automation_enabled"
        )
        .eq("owner_user_id", str(user_id))
        .execute()
    ).data or []
    if not rows:
        raise AccountError("no linked account")
    row = rows[0]
    return {
        "id": row["id"],
        "label": row.get("label"),
        "league_id": row.get("league_id"),
        "season": row.get("season"),
        "espn_s2": decrypt_secret(row["espn_s2_enc"]),
        "swid": decrypt_secret(row["swid_enc"]),
        "lineup_automation_enabled": bool(row.get("lineup_automation_enabled")),
    }


def link_account_to_owner(supabase, token: str, user_id: str) -> tuple[str, dict]:
    """Link the account a personal token names to a Commons user, once.

    The token is only hashed and compared; it is never stored. Only
    owner_user_id changes: cookies, automation and team claims are untouched.
    Returns (outcome, {"id", "label"}); outcome is linked | already_linked |
    other_owner. Raises AccountError when the token is unknown.
    """
    row = get_account_row_by_token(supabase, token)
    outcome = supabase.rpc(
        "espn_link_account", {"p_account_id": row["id"], "p_user_id": str(user_id)}
    ).execute().data
    if outcome == "missing":
        raise AccountError("unknown token")
    return outcome, row


def swid_key(swid: str) -> str:
    """One SWID's canonical form: upper-case ASCII without braces."""
    value = swid.strip().strip("{}").strip()
    return value.upper() if value.isascii() else value


def _accounts_for_team(supabase, swid: str, league_id: int, season: int) -> list[dict]:
    # swid is Fernet-encrypted with a random IV, so rows are matched by
    # decrypting the SWIDs of the few that share the league and season; no
    # espn_s2 is decrypted here. A row that will not decrypt (a key mismatch)
    # is skipped; at worst it leads to a duplicate row.
    rows = (
        supabase.table("espn_accounts")
        .select("id,label,swid_enc,owner_user_id,owner_proven")
        .eq("league_id", league_id)
        .eq("season", season)
        .execute()
    ).data or []
    wanted, matches = swid_key(swid), []
    for row in rows:
        try:
            stored = decrypt_secret(row["swid_enc"])
        except AccountError:
            logger.warning("Skipping ESPN account %s: its SWID does not decrypt", row["id"])
            continue
        if swid_key(stored) == wanted:
            matches.append(row)
    return matches


def connect_account_for_owner(
    supabase, user_id: str, *, league_id, season, espn_s2: str, swid: str,
    swid_proven: bool, enable_automation: bool = True,
) -> tuple[str, dict]:
    """Link one ESPN league team to a Commons user from working session cookies.

    This is the web replacement for presenting a cce_ token. The cookies are
    probed against the league first, which proves only that they can read it:
    the league's mTeam view lists every member's SWID. swid_proven says the SWID
    came from a MyDisney login, the only proof that the caller owns it.

    - A proven claim links an unowned row for the SWID, league and season, or
      takes over a row whose owner is unproven (espn_claim_account_proven); a
      proven owner is never displaced.
    - An unproven claim (typed cookies) creates a new row, or refreshes the
      caller's own row; it never claims a row that already exists.
    - New cookies written into an existing row retire its cce_ token, so they
      reach no one but the linked Commons user. A proven claim commits them with
      the ownership change in one transaction. A stored espn_s2 is read only on
      the caller's own row.

    Returns (outcome, summary); outcome is linked | taken_over | already_linked
    | other_owner | unproven. Raises AccountError for invalid fields and
    EspnAuthError / EspnError when ESPN refuses or does not answer.
    """
    league_id = _coerce_int(league_id, "league_id")
    season = _coerce_int(season, "season")
    if league_id <= 0 or not 2019 <= season <= 2100:
        raise AccountError("league_id or season out of range")
    espn_s2, swid = (espn_s2 or "").strip(), (swid or "").strip()
    if not espn_s2 or not swid or not (espn_s2.isascii() and swid.isascii()):
        raise AccountError("espn_s2 and SWID are required")
    EspnClient.probe(espn_s2, swid, league_id, season)

    matches = _accounts_for_team(supabase, swid, league_id, season)
    row = next((r for r in matches if r.get("owner_user_id") == str(user_id)), None)
    if row is None and matches:
        if any(r.get("owner_user_id") and r.get("owner_proven") for r in matches):
            return "other_owner", {"id": matches[0]["id"], "label": matches[0].get("label")}
        if not swid_proven:
            return "unproven", {"id": matches[0]["id"], "label": matches[0].get("label")}
        row = next((r for r in matches if not r.get("owner_user_id")), matches[0])
    mine = row is not None and row.get("owner_user_id") == str(user_id)
    # Read a stored espn_s2 only on the caller's own row, to skip a write when nothing changed.
    unchanged = mine and hmac.compare_digest(_stored_espn_s2(supabase, row["id"], user_id).encode(), espn_s2.encode())
    cookies, token = encrypt_secret(espn_s2), mint_token()  # the new token is never shown
    if row:
        account = {"id": row["id"], "label": row.get("label")}
    else:
        created = (supabase.table("espn_accounts").insert({
            "label": "espn",
            "league_id": league_id,
            "season": season,
            "espn_s2_enc": cookies,
            "swid_enc": encrypt_secret(swid),
            "token_hash": hash_token(token),
            "token_prefix": token[:12],
            "lineup_automation_enabled": bool(enable_automation),
        }).execute().data or [{}])[0]
        if not created.get("id"):
            raise AccountError("could not create the ESPN account")
        account = {"id": created["id"], "label": "espn"}
    summary = {**account, "league_id": league_id, "season": season}
    if swid_proven:
        # Ownership, cookies, the replacement token, the automation choice, proposal expiry and the
        # detaching of unproven duplicates commit together in one transaction, or not at all.
        outcome = supabase.rpc("espn_claim_account_proven", {
            "p_account_id": account["id"], "p_user_id": str(user_id), "p_espn_s2_enc": cookies,
            "p_token_hash": hash_token(token), "p_token_prefix": token[:12],
            "p_automation": bool(enable_automation), "p_refresh_own": not unchanged,
            "p_duplicate_ids": [r["id"] for r in matches if r["id"] != account["id"]],
        }).execute().data
        if outcome not in ("linked", "taken_over", "already_linked", "other_owner"):
            raise AccountError("could not link the ESPN account")
        return outcome, summary
    if row is None:  # a row this request just created: link it like any new account
        outcome = supabase.rpc(
            "espn_link_account", {"p_account_id": account["id"], "p_user_id": str(user_id)}
        ).execute().data
        if outcome not in ("linked", "already_linked", "other_owner"):
            raise AccountError("could not link the ESPN account")
        return outcome, summary
    # Typed cookies refresh an existing row only while it is still the caller's: one UPDATE filtered
    # on their ownership, never a link, so a row a proven claim detached meanwhile cannot be
    # re-acquired. With unchanged cookies the update rewrites only the owner, to confirm it.
    write = ({"owner_user_id": str(user_id)} if unchanged else
             {"espn_s2_enc": cookies, "token_hash": hash_token(token), "token_prefix": token[:12]})
    kept = supabase.table("espn_accounts").update(write).eq(
        "id", row["id"]).eq("owner_user_id", str(user_id)).execute().data
    return ("already_linked" if kept else "unproven"), summary


def _stored_espn_s2(supabase, account_id, user_id) -> str:
    stored = (
        supabase.table("espn_accounts").select("espn_s2_enc")
        .eq("id", account_id).eq("owner_user_id", str(user_id)).execute()
    ).data or []
    return decrypt_secret(stored[0]["espn_s2_enc"]) if stored else ""


def make_client_for_account(account: dict, *, cooldown: RequestCooldown | None = None) -> EspnClient:
    """Build the per-user client from a resolved account dict."""
    return EspnClient(
        account["espn_s2"], account["swid"], account["league_id"], account["season"],
        cooldown=cooldown,
    )


def delete_account(supabase, account_id) -> str:
    """Delete one account row (self-service disconnect).

    The caller's token resolved to this account, so an account can only
    ever delete itself. Everything attached to the row goes with it:
    espn_snapshots and espn_lineup_runs declare
    ``account_id ... references espn_accounts(id) on delete cascade``
    (migrations 0007/0008), so Postgres removes the account's snapshot
    history and lineup run log as part of the same delete. The
    service-role delete grant on espn_accounts itself is migration 0013.
    Once the row is gone the token hash is gone too, so the token
    resolves to nothing and every later request with it is a 401.
    """
    supabase.table("espn_accounts").delete().eq("id", account_id).execute()
    return account_id


# --- lineup automation opt-in -------------------------------------------------


def set_lineup_automation(supabase, account_id, enabled: bool) -> bool:
    """Set the daily-lineup automation flag for one account."""
    supabase.table("espn_accounts").update(
        {"lineup_automation_enabled": bool(enabled)}
    ).eq("id", account_id).execute()
    return bool(enabled)


def list_lineup_automation_accounts(supabase) -> list[dict]:
    """All accounts opted into daily lineup automation (cookies decrypted).

    Used only by the optional batch entrypoint (jobs/espn_lineup.py),
    which runs server-side with the service key; the returned dicts
    carry the same shape as :func:`get_account_by_token` results.
    """
    res = (
        supabase.table("espn_accounts")
        .select(
            "id,label,league_id,season,espn_s2_enc,swid_enc,"
            "lineup_automation_enabled"
        )
        .eq("lineup_automation_enabled", True)
        .execute()
    )
    accounts = []
    for row in res.data or []:
        accounts.append(
            {
                "id": row["id"],
                "label": row.get("label"),
                "league_id": row.get("league_id"),
                "season": row.get("season"),
                "espn_s2": decrypt_secret(row["espn_s2_enc"]),
                "swid": decrypt_secret(row["swid_enc"]),
                "lineup_automation_enabled": True,
            }
        )
    return accounts
