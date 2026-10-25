"""Server-side MyDisney (Disney ID) login for ESPN onboarding.

The cookie onboarding flow (see accounts.py) asks users to hand-extract
``espn_s2`` / ``SWID`` cookies from their browser's DevTools — a dead end
for non-technical users. This module is the friendly front door: the user
gives us their ESPN email + password once, we run the MyDisney login
server-side against Disney's ``jgc`` API (the same API the ESPN web
login uses, client ``ESPN-ONESITE.WEB-PROD``), harvest the two session
cookies from the response, and hand them to the existing
:func:`espn.accounts.create_account` probe/store path. Nothing else in
the system changes: cookies remain the only stored secret.

Password hygiene (hard requirements):

- The password is used for exactly this one login and is never stored,
  never logged, and never included in an exception message. Nothing in
  this module logs at all, and no route logs request bodies.
- Exactly ONE ``guest/login`` attempt per call — no retries. Disney
  locks accounts after repeated failed logins, and a retry loop here
  could lock a user out of their own ESPN account.

Login call sequence (verified live 2026-10-25):

1. ``POST /jgc/v6/client/ESPN-ONESITE.WEB-PROD/api-key?langPref=en-US``
   with an empty JSON body; Disney returns a short-lived key in the
   ``api-key`` response header.
2. ``POST /jgc/v6/client/ESPN-ONESITE.WEB-PROD/guest/login`` with
   ``Authorization: APIKEY <key>`` and JSON
   ``{"loginValue": email, "password": password}``. On success Disney
   sets the ``espn_s2`` and ``SWID`` cookies. On failure it answers
   4xx with a JSON error envelope whose ``error.errors[].code`` names
   the cause (e.g. ``AUTHORIZATION_CREDENTIALS`` for a bad password —
   confirmed with a live negative probe).

League discovery reads the ESPN fan API
(``fan.api.espn.com/apis/v2/fans/{SWID}``) with the fresh session
cookies: its ``preferences`` list carries one "Fantasy League Manager"
entry per league membership, with the league id/name and the member's
team id/name under ``metaData.entry``. Basketball entries are the ones
whose entry ``abbrev`` is ``FBA``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .espn_client import USER_AGENT

DISNEY_BASE = (
    "https://registerdisney.go.com/jgc/v6/client/ESPN-ONESITE.WEB-PROD"
)
FAN_API_BASE = "https://fan.api.espn.com/apis/v2/fans"
_TIMEOUT_S = 20

# Substrings of Disney error codes that mean "the user must resolve
# something on Disney's side" (verification challenge, passcode, or a
# locked account) — this form cannot complete those.
_CHALLENGE_MARKERS = (
    "CHALLENGE",
    "VERIFICATION",
    "VERIFY",
    "RESCUE",
    "PASSCODE",
    "ONE_TIME",
    "OTP",
    "MFA",
    "STEP_UP",
    "LOCKED",
    "LOCKOUT",
)
_NOT_FOUND_MARKERS = (
    "NOT_FOUND",
    "NO_ACCOUNT",
    "ACCOUNT_NOT_FOUND",
    "USER_NOT_FOUND",
    "DOES_NOT_EXIST",
)


class DisneyLoginError(Exception):
    """Disney-side failure: unreachable, 5xx, or an unparseable reply."""


class InvalidCredentialsError(DisneyLoginError):
    """Disney rejected the email/password pair."""


class AccountNotFoundError(DisneyLoginError):
    """Disney has no account for that email."""


class ChallengeRequiredError(DisneyLoginError):
    """Disney demands verification (challenge/passcode/locked account)."""


# --- transport seam (monkeypatched in tests) ---------------------------------


def _open(req: urllib.request.Request):
    return urllib.request.urlopen(req, timeout=_TIMEOUT_S)


def _request(method: str, url: str, body: dict | None, headers: dict | None = None):
    """One round-trip; returns (status, headers, text) without raising.

    HTTP error statuses are returned, not raised; transport failures
    become DisneyLoginError. Response bodies are returned raw — callers
    must take care never to echo them into logs or messages when the
    request carried credentials (Disney error envelopes are safe: they
    contain error codes, never the submitted password).
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _open(req) as resp:
            return resp.status, resp.headers, resp.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return e.code, e.headers, text
    except urllib.error.URLError as e:
        raise DisneyLoginError(
            f"could not reach Disney's login service ({e.reason})"
        ) from e


def _absorb_cookies(headers, store: dict) -> None:
    """Collect name=value pairs from Set-Cookie headers into ``store``."""
    if headers is None:
        return
    get_all = getattr(headers, "get_all", None)
    values = get_all("Set-Cookie") if get_all else []
    for value in values or []:
        pair = value.split(";", 1)[0]
        name, sep, val = pair.partition("=")
        if sep:
            store[name.strip()] = val.strip()


def _error_codes(payload) -> list[str]:
    codes = []
    if isinstance(payload, dict):
        error = payload.get("error")
        errors = error.get("errors") if isinstance(error, dict) else None
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict) and item.get("code"):
                    codes.append(str(item["code"]))
    return codes


def _classify(status: int, payload) -> DisneyLoginError:
    """Map a failed Disney login response onto the outcome taxonomy."""
    codes = _error_codes(payload)
    for code in codes:
        upper = code.upper()
        if upper == "AUTHORIZATION_CREDENTIALS":
            return InvalidCredentialsError(
                "Disney rejected the email/password pair"
            )
        if any(marker in upper for marker in _NOT_FOUND_MARKERS):
            return AccountNotFoundError("no Disney account for that email")
        if any(marker in upper for marker in _CHALLENGE_MARKERS):
            return ChallengeRequiredError(
                "Disney requires additional verification for this account"
            )
    suffix = f" (Disney error code: {codes[0]})" if codes else ""
    return DisneyLoginError(f"Disney login failed (HTTP {status}){suffix}")


def _find_swid(node) -> str | None:
    """Recursively look for a SWID-shaped value in a login response."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                isinstance(key, str)
                and key.lower() == "swid"
                and isinstance(value, str)
                and value.startswith("{")
            ):
                return value
            found = _find_swid(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_swid(item)
            if found:
                return found
    return None


# --- the login ---------------------------------------------------------------


def login(email: str, password: str) -> dict:
    """Log in to MyDisney once; return {"espn_s2", "swid"}.

    The password lives only in this call frame and the single request
    body built from it. Raises InvalidCredentialsError /
    AccountNotFoundError / ChallengeRequiredError for the user-facing
    outcomes and DisneyLoginError for everything upstream.
    """
    email = (email or "").strip()
    if not email or not password:
        raise DisneyLoginError("email and password are required")

    cookies: dict[str, str] = {}

    # Step 1: bootstrap the short-lived API key (not a login attempt).
    status, headers, _ = _request(
        "POST", f"{DISNEY_BASE}/api-key?langPref=en-US", {}
    )
    _absorb_cookies(headers, cookies)
    if status != 200:
        raise DisneyLoginError(
            f"Disney login bootstrap failed (HTTP {status})"
        )
    api_key = headers.get("api-key") if headers is not None else None
    if not api_key:
        raise DisneyLoginError("Disney did not issue an API key")

    # Step 2: exactly one login attempt.
    status, headers, text = _request(
        "POST",
        f"{DISNEY_BASE}/guest/login?langPref=en-US",
        {"loginValue": email, "password": password},
        {"Authorization": f"APIKEY {api_key}"},
    )
    _absorb_cookies(headers, cookies)
    try:
        payload = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        payload = None
    if status != 200 or (isinstance(payload, dict) and payload.get("error")):
        raise _classify(status, payload)

    espn_s2 = cookies.get("espn_s2")
    swid = cookies.get("SWID") or cookies.get("swid") or _find_swid(payload)
    if not espn_s2 or not swid:
        raise DisneyLoginError(
            "Disney login succeeded but did not issue the ESPN session "
            "cookies (espn_s2/SWID)"
        )
    return {"espn_s2": espn_s2, "swid": swid}


# --- league discovery ----------------------------------------------------------


def discover_basketball_leagues(espn_s2: str, swid: str, season: int) -> list:
    """The account's fantasy basketball leagues for ``season``.

    Reads the fan API with the fresh session cookies and returns one
    {"league_id", "name", "team_id", "team_name"} dict per league the
    account belongs to in that season (deduplicated by league id).
    A 404 / no-memberships answer is an empty list; transport and
    server failures raise DisneyLoginError.
    """
    url = f"{FAN_API_BASE}/{urllib.parse.quote(swid, safe='')}"
    status, _headers, text = _request(
        "GET",
        url,
        None,
        {"Cookie": f"espn_s2={espn_s2}; SWID={swid}"},
    )
    if status == 404:
        return []
    if status != 200:
        raise DisneyLoginError(
            f"ESPN league discovery failed (HTTP {status})"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise DisneyLoginError("ESPN league discovery returned non-JSON") from e

    leagues: list[dict] = []
    seen: set[int] = set()
    preferences = payload.get("preferences") if isinstance(payload, dict) else None
    for pref in preferences or []:
        if not isinstance(pref, dict):
            continue
        ptype = pref.get("type")
        if not isinstance(ptype, dict) or ptype.get("code") != "fantasy":
            continue
        entry = ((pref.get("metaData") or {}).get("entry")) or {}
        if entry.get("abbrev") != "FBA" or entry.get("seasonId") != season:
            continue
        team_name = (entry.get("entryMetadata") or {}).get("teamName")
        for group in entry.get("groups") or []:
            if not isinstance(group, dict):
                continue
            league_id = group.get("groupId")
            if not isinstance(league_id, int) or league_id in seen:
                continue
            seen.add(league_id)
            leagues.append(
                {
                    "league_id": league_id,
                    "name": group.get("groupName"),
                    "team_id": entry.get("entryId"),
                    "team_name": team_name,
                }
            )
    return leagues
