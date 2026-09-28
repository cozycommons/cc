"""Minimal Resy API client (unofficial, reverse-engineered).

Resy has no public API (Amex-owned, partner-only). Everything here runs on the
unofficial ``https://api.resy.com`` surface, mapped from the open-source
reference implementations (aaymeloglu/restaurant-mcp, chrischall/resy-mcp,
zjweiss/resy-bot). It is undocumented, unsupported, and may change without
notice — this client fails loudly on unexpected shapes rather than guessing.

Auth model:
  - a PUBLIC api key, shipped in resy.com's own web client ("public by
    design"). Read from the RESY_API_KEY env var; never hardcoded.
  - a per-user auth token from ``POST /3/auth/password`` (email + password).
    Tokens expire; on 401/419 the client re-logs-in once from the stored
    email/password and retries once. Dead credentials raise ResyAuthError
    (the user must re-onboard).

Request pacing: Resy rate-limits aggressively (documented 429s after rapid
bursts; reference clients self-limit to ~20 req/min). MIN_GAP_S keeps one
client at a polite pace. One ResyClient = one Resy account; pacing state is
per-instance and nothing is shared across accounts. Tokens and passwords are
never logged.

Headers (from the reference clients):
  Authorization: ResyAPI api_key="<key>"
  x-resy-auth-token / x-resy-universal-auth: <user token>
  Origin: https://resy.com, Referer: https://resy.com/, x-origin, browser UA
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.resy.com"
ORIGIN = "https://resy.com"
REFERER = "https://resy.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Reference clients self-limit to ~20 req/min; stay at or under that.
MIN_GAP_S = 3.0


class ResyError(Exception):
    """Non-auth Resy API failure (carries HTTP status when known)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ResyUnauthorized(ResyError):
    """The auth token was rejected (triggers one re-login + retry)."""


class ResyAuthError(ResyError):
    """The stored credentials are dead — the user must re-onboard."""


def resy_api_key() -> str:
    """The public Resy web-client API key (env var; never hardcoded)."""
    key = os.environ.get("RESY_API_KEY", "").strip()
    if not key:
        raise ResyError(
            "RESY_API_KEY is not set. It is Resy's public web-client key "
            "(shipped in resy.com's own JS); extract it from a logged-in "
            "resy.com devtools session per the reference clients and set it "
            "as an env var."
        )
    return key


def _read_json_response(resp) -> object:
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ResyError(f"Resy returned non-JSON: {e}")


class ResyClient:
    """Authenticated Resy API access for a single Resy account."""

    def __init__(
        self,
        auth_token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        on_token_refresh=None,
    ):
        self._api_key = resy_api_key()
        self._auth_token = auth_token
        self._email = email
        self._password = password
        # on_token_refresh(new_token): called when a fresh token is minted so
        # the caller can persist it. Best-effort.
        self._on_token_refresh = on_token_refresh
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    # -- internals ---------------------------------------------------------
    def _pace(self) -> None:
        with self._lock:
            wait = MIN_GAP_S - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
            "Origin": ORIGIN,
            "Referer": REFERER,
            "x-origin": ORIGIN,
            "Authorization": f'ResyAPI api_key="{self._api_key}"',
        }
        if self._auth_token:
            headers["x-resy-auth-token"] = self._auth_token
            headers["x-resy-universal-auth"] = self._auth_token
        return headers

    def _raw(self, method: str, path: str, *, params=None, form=None, what: str):
        """One HTTP round-trip; no auth retry (see _request)."""
        self._pace()
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = self._headers()
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _read_json_response(resp)
        except urllib.error.HTTPError as e:
            if e.code in (401, 419):
                raise ResyUnauthorized(f"{what} -> {e.code}", status=e.code)
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                detail = ""
            raise ResyError(f"{what} -> {e.code} {detail}", status=e.code)
        except urllib.error.URLError as e:
            raise ResyError(f"{what}: network error {e}")

    def _request(self, method: str, path: str, *, params=None, form=None,
                 what: str, auth: bool = True, _retried: bool = False):
        """Request with one re-login + retry on 401/419.

        Never loops: a second auth failure means the credentials are dead.
        """
        if auth and not self._auth_token:
            self.login()
        try:
            return self._raw(method, path, params=params, form=form, what=what)
        except ResyUnauthorized:
            if _retried or not (self._email and self._password):
                raise ResyAuthError(
                    "Resy session expired and no stored credentials to refresh; "
                    "re-onboard to continue"
                )
            self.login()  # raises ResyAuthError when the password is dead
            return self._raw(
                method, path, params=params, form=form, what=what
            )

    # -- auth --------------------------------------------------------------
    def login(self) -> str:
        """Log in with the stored email/password; returns the fresh token.

        Validates the session end-to-end with a /2/user probe before
        returning, so only working credentials are ever persisted.
        """
        if not (self._email and self._password):
            raise ResyAuthError("no Resy credentials stored; re-onboard to continue")
        try:
            data = self._raw(
                "POST",
                "/3/auth/password",
                form={"email": self._email, "password": self._password},
                what="Resy login",
            )
        except ResyUnauthorized as e:
            raise ResyAuthError("Resy rejected the stored credentials") from e
        token = None
        if isinstance(data, dict):
            token = data.get("token") or data.get("auth_token")
            if not token and isinstance(data.get("id"), dict):
                token = data["id"].get("token")
        if not token:
            raise ResyAuthError("Resy login returned no token")
        self._auth_token = token
        # probe: raises if the token doesn't actually work
        self._raw("GET", "/2/user", what="Resy session probe")
        if self._on_token_refresh is not None:
            try:
                self._on_token_refresh(token)
            except Exception:
                pass  # best-effort: the fresh token still works this request
        return token

    @staticmethod
    def login_with(email: str, password: str) -> "ResyClient":
        """Log in with fresh credentials; returns a validated client.

        Used once at onboarding — the caller persists the encrypted
        credentials and the minted token.
        """
        email = (email or "").strip()
        if not email or "@" not in email:
            raise ResyError("a valid email is required")
        if not password:
            raise ResyError("password is required")
        client = ResyClient(email=email, password=password)
        client.login()  # raises ResyAuthError / ResyError on failure
        return client

    # -- public read API ----------------------------------------------------
    def search(self, query: str, lat: float, lng: float, day: str,
               party_size: int) -> list:
        """Venue search near a point, with slots for the day baked in."""
        data = self._raw(
            "GET",
            "/4/find",
            params={
                "lat": lat,
                "long": lng,
                "day": day,
                "party_size": party_size,
                "query": query or "",
            },
            what="Resy search",
        )
        if not isinstance(data, dict):
            raise ResyError("Resy search: unexpected response")
        venues = (data.get("results") or {}).get("venues") or []
        return venues if isinstance(venues, list) else []

    def find_slots(self, venue_id: int, day: str, party_size: int) -> list:
        """Available slots at one venue: [{config.token, config.type, ...}]."""
        data = self._request(
            "GET",
            "/4/find",
            params={
                "lat": 0,
                "long": 0,
                "day": day,
                "party_size": party_size,
                "venue_id": int(venue_id),
            },
            what="Resy find slots",
        )
        if not isinstance(data, dict):
            raise ResyError("Resy find slots: unexpected response")
        venues = (data.get("results") or {}).get("venues") or []
        if not venues:
            return []
        slots = (venues[0] or {}).get("slots") or []
        return slots if isinstance(slots, list) else []

    def get_venue(self, venue_id: int) -> dict | None:
        """Venue detail: name, cuisine, price_range, rating, neighborhood."""
        data = self._request(
            "GET", "/3/venue", params={"id": int(venue_id)}, what="Resy venue"
        )
        if not isinstance(data, dict):
            return None
        venue = data.get("venue")
        return venue if isinstance(venue, dict) else None

    def get_user(self) -> dict:
        """Profile + saved payment methods (/2/user)."""
        data = self._request("GET", "/2/user", what="Resy user")
        if not isinstance(data, dict):
            raise ResyError("Resy user: unexpected response")
        return data

    def get_reservations(self) -> list:
        """The user's reservations (all scopes; filter client-side)."""
        data = self._request(
            "GET", "/3/user/reservations", what="Resy reservations"
        )
        if not isinstance(data, dict):
            raise ResyError("Resy reservations: unexpected response")
        reservations = data.get("reservations") or []
        venues = data.get("venues") or {}
        out = []
        for r in reservations if isinstance(reservations, list) else []:
            if not isinstance(r, dict):
                continue
            venue = {}
            vid = (r.get("venue") or {}).get("id")
            if vid is not None and isinstance(venues, dict):
                v = venues.get(str(vid))
                if isinstance(v, dict):
                    venue = v
            out.append({"reservation": r, "venue": venue})
        return out

    # -- booking ------------------------------------------------------------
    def get_book_details(self, config_token: str, day: str,
                         party_size: int) -> dict:
        """Exchange a slot's config token for a book_token (+ venue info)."""
        data = self._request(
            "GET",
            "/3/details",
            params={
                "config_id": config_token,
                "day": day,
                "party_size": party_size,
            },
            what="Resy book details",
        )
        if not isinstance(data, dict) or not isinstance(
            data.get("book_token"), dict
        ):
            raise ResyError("Resy details: no book_token returned")
        return data

    def book(self, book_token: str, payment_method_id: int) -> dict:
        """Finalize a reservation. Returns {resy_token, reservation_id, ...}."""
        data = self._request(
            "POST",
            "/3/book",
            form={
                "book_token": book_token,
                "struct_payment_method": json.dumps({"id": int(payment_method_id)}),
                "source_id": "resy.com-venue-details",
            },
            what="Resy book",
        )
        if not isinstance(data, dict) or not data.get("resy_token"):
            raise ResyError("Resy book: unexpected response")
        return data

    def cancel(self, resy_token: str) -> dict:
        """Cancel a reservation by its resy_token."""
        data = self._request(
            "POST",
            "/3/cancel",
            form={"resy_token": resy_token},
            what="Resy cancel",
        )
        return data if isinstance(data, dict) else {}
