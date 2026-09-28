"""Minimal Partiful API client (unofficial, reverse-engineered).

Partiful is a Firebase app (project ``getpartiful``). Its API is a set of
Firebase Cloud Functions at ``POST https://api.partiful.com/<functionName>``:

- headers: ``Authorization: Bearer <firebase-id-token>``,
  ``Content-Type: application/json``, ``Origin: https://partiful.com``,
  ``Referer: https://partiful.com/``
- body: ``{"data": {"params": {...}, "userId": "<firebase-uid>"}}``
- response: ``{"result": {"data": <payload>}}``

Auth is Firebase phone/SMS OTP:
  1. ``sendAuthCodeTrusted`` sends the SMS (no auth needed)
  2. ``getLoginToken`` exchanges phone+code for a Firebase custom token
  3. Google Identity Toolkit ``signInWithCustomToken`` exchanges that for a
     short-lived JWT (~1h) + a long-lived refresh token
  4. Google Secure Token Service trades the refresh token for fresh JWTs
     (``Referer: https://partiful.com/`` is REQUIRED or Google 403s)

One PartifulClient instance = one Partiful account. Token state and request
pacing are per-instance (the backend is multi-tenant; nothing is shared across
accounts). Tokens are never logged.

Read-only: this client exposes no write endpoints.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# Public Firebase web API key, embedded in partiful.com's web app.
FIREBASE_API_KEY = "AIzaSyCky6PJ7cHRdBKk5X7gjuWERWaKWBHr4_k"
API_BASE = "https://api.partiful.com"
IDENTITY_TOOLKIT_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
    f"?key={FIREBASE_API_KEY}"
)
SECURE_TOKEN_URL = (
    f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
)
ORIGIN = "https://partiful.com"
REFERER = "https://partiful.com/"
MIN_GAP_S = 0.25


class PartifulError(Exception):
    """Non-auth Partiful API failure (carries HTTP status when known)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PartifulUnauthorized(PartifulError):
    """The ID token was rejected (triggers a refresh + one retry)."""


class PartifulAuthError(PartifulError):
    """The refresh token is dead — the user must re-onboard."""


def normalize_phone(value: str) -> str:
    """Normalize a phone number to +E.164.

    Accepts 10-digit US numbers (assumes +1) or a leading-+ international
    number. Raises PartifulError on anything else.
    """
    raw = (value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and 7 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise PartifulError("phone number must be 10 digits (US) or +E.164")


def _read_json_response(resp) -> object:
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise PartifulError(f"Partiful returned non-JSON: {e}")


class PartifulClient:
    """Authenticated Partiful API access for a single Partiful account."""

    def __init__(self, refresh_token: str, uid: str, on_refresh=None):
        self.uid = uid
        self._refresh_token = refresh_token
        # on_refresh(new_refresh_token): called when Google rotates the
        # refresh token so the caller can persist it. Best-effort.
        self._on_refresh = on_refresh
        self._lock = threading.Lock()
        self._last_call_at = 0.0
        self._id_token: str | None = None
        self._id_token_exp = 0.0

    # -- internals ---------------------------------------------------------
    def _pace(self) -> None:
        with self._lock:
            wait = MIN_GAP_S - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()

    def _post(
        self,
        url: str,
        *,
        json_body: object = None,
        form_body: dict | None = None,
        headers: dict | None = None,
        what: str,
    ) -> object:
        self._pace()
        if form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
            content_type = "application/json"
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", content_type)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _read_json_response(resp)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PartifulUnauthorized(f"{what} -> {e.code}", status=e.code)
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            raise PartifulError(f"{what} -> {e.code} {detail}", status=e.code)
        except urllib.error.URLError as e:
            raise PartifulError(f"{what}: network error {e}")

    def _refresh_id_token(self) -> str:
        """Trade the stored refresh token for a fresh JWT (Google STS).

        Persists a rotated refresh token via on_refresh. Raises
        PartifulAuthError when the refresh token is dead.
        """
        try:
            data = self._post(
                SECURE_TOKEN_URL,
                form_body={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                headers={"Referer": REFERER},
                what="Partiful token refresh",
            )
        except PartifulUnauthorized as e:
            raise PartifulAuthError(
                "Partiful session expired; re-onboard to continue"
            ) from e
        except PartifulError as e:
            # Google answers invalid/expired grants with 400
            if e.status in (400, 401, 403):
                raise PartifulAuthError(
                    "Partiful refresh token rejected; re-onboard to continue"
                ) from e
            raise
        if not isinstance(data, dict) or not data.get("id_token"):
            raise PartifulError("Partiful token refresh returned no id_token")
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            if self._on_refresh is not None:
                try:
                    self._on_refresh(new_refresh)
                except Exception:
                    pass  # best-effort: the fresh JWT still works this request
        self._id_token = data["id_token"]
        try:
            ttl = float(data.get("expires_in", "3600"))
        except (TypeError, ValueError):
            ttl = 3600.0
        self._id_token_exp = time.time() + max(ttl - 60, 60)
        return self._id_token

    def ensure_id_token(self, force: bool = False) -> str:
        if self._id_token and not force and self._id_token_exp - time.time() > 0:
            return self._id_token
        self._id_token = None
        return self._refresh_id_token()

    def _function_call(self, function_name: str, params: dict, id_token: str) -> object:
        data = self._post(
            f"{API_BASE}/{function_name}",
            json_body={"data": {"params": params, "userId": self.uid}},
            headers={
                "Authorization": f"Bearer {id_token}",
                "Origin": ORIGIN,
                "Referer": REFERER,
            },
            what=f"Partiful {function_name}",
        )
        if not isinstance(data, dict) or "result" not in data:
            raise PartifulError(f"Partiful {function_name}: unexpected response envelope")
        return data["result"].get("data")

    # -- public read API ----------------------------------------------------
    def call(self, function_name: str, params: dict) -> object:
        """Call a Partiful Cloud Function; refreshes the JWT once on 401/403.

        A second auth failure means the refresh token is dead (re-onboard);
        it never loops.
        """
        token = self.ensure_id_token()
        try:
            return self._function_call(function_name, params, token)
        except PartifulUnauthorized:
            token = self.ensure_id_token(force=True)
        try:
            return self._function_call(function_name, params, token)
        except PartifulUnauthorized as e:
            raise PartifulAuthError(
                "Partiful session expired; re-onboard to continue"
            ) from e

    def get_my_rsvps(self) -> list:
        """Every event the user was invited to or RSVP'd to (any status).

        Each entry carries the user's own RSVP as ``guest: {status, ...}``.
        """
        data = self.call("getMyRsvps", {})
        events = (data or {}).get("events") if isinstance(data, dict) else None
        return events if isinstance(events, list) else []

    def get_published_events(self) -> list:
        """Events the user hosts. Responds with a bare array."""
        data = self.call("getPublishedEvents", {"userId": self.uid})
        return data if isinstance(data, list) else []

    def get_event_info(self, event_id: str) -> dict:
        """Detail for one viewable event: {event, passwordRequired}."""
        data = self.call("getEventInfo", {"eventId": event_id})
        if not isinstance(data, dict):
            raise PartifulError("Partiful getEventInfo: unexpected response")
        return data

    # -- onboarding (static; no account state) ------------------------------
    @staticmethod
    def send_auth_code(phone: str) -> None:
        """Send the SMS verification code. No auth needed."""
        client = PartifulClient.__new__(PartifulClient)
        client._lock = threading.Lock()
        client._last_call_at = 0.0
        client._post(
            f"{API_BASE}/sendAuthCodeTrusted",
            json_body={"data": {"params": {"phoneNumber": phone}}},
            what="Partiful sendAuthCodeTrusted",
        )

    @staticmethod
    def verify_auth_code(phone: str, code: str) -> dict:
        """Exchange phone+SMS code for {"refresh_token", "uid"}.

        Validates the session end-to-end with a getMyRsvps probe before
        returning, so only working credentials are ever stored.
        """
        client = PartifulClient.__new__(PartifulClient)
        client._lock = threading.Lock()
        client._last_call_at = 0.0
        data = client._post(
            f"{API_BASE}/getLoginToken",
            json_body={"data": {"params": {"phoneNumber": phone, "authCode": code}}},
            what="Partiful getLoginToken",
        )
        custom_token = (
            data.get("result", {}).get("data", {}).get("customToken")
            if isinstance(data, dict)
            else None
        )
        if not custom_token:
            raise PartifulError("wrong or expired SMS code")
        data = client._post(
            IDENTITY_TOOLKIT_URL,
            json_body={"token": custom_token, "returnSecureToken": True},
            headers={"Referer": REFERER},
            what="Partiful signInWithCustomToken",
        )
        if not isinstance(data, dict) or not data.get("refreshToken"):
            raise PartifulError("Partiful sign-in returned no refresh token")
        refresh_token = data["refreshToken"]
        uid = data.get("localId") or ""
        if not uid:
            raise PartifulError("Partiful sign-in returned no user id")
        probe = PartifulClient(refresh_token, uid)
        # reuse the just-minted JWT for the probe instead of refreshing again
        probe._id_token = data.get("idToken")
        probe._id_token_exp = time.time() + 3300
        probe.get_my_rsvps()  # raises if the session doesn't work
        return {"refresh_token": refresh_token, "uid": uid}
