"""Minimal Beli API client.

Python port of the beli-recs TypeScript client. Mirrors the behavior of the
unofficial beli-api SDK (ProjectBarks/beli-api, MIT), reverse-engineered from
the Beli mobile app's traffic:

- every request carries a realistic browser User-Agent and
  ``Origin: capacitor://localhost`` (the API 403s requests without them)
- requests are spaced >=350ms apart (the API throttles bursts)
- SimpleJWT auth: POST /api/token/ {email|phone_no, password} -> {access, refresh}
  access tokens last ~20 min; refresh tokens last 7 days and are not rotated.

One BeliClient instance = one Beli account. Token state and request pacing are
per-instance (the backend is multi-tenant; nothing is shared across accounts).
"""

from __future__ import annotations

import base64
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

API_HOST = "https://backoffice-service-t57o3dxfca-nn.a.run.app"
ONBOARD_HOST = "https://backoffice-service-onboarding-t57o3dxfca-nn.a.run.app"
ORIGIN = "capacitor://localhost"
MIN_GAP_S = 0.35

USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 16; SM-S928U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.91 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.15",
]

_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,20}$")


class BeliError(Exception):
    """Non-auth Beli API failure (carries HTTP status when known)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class BeliUnauthorized(BeliError):
    """The access token was rejected (triggers a re-login)."""


def is_phone_identifier(value: str) -> bool:
    """True when the login identifier looks like a phone number, not an email."""
    v = value.strip()
    return bool(_PHONE_RE.match(v)) and any(c.isdigit() for c in v) and "@" not in v


def login_body(beli_id: str, password: str) -> dict:
    """Beli's token endpoint accepts either {email, password} or {phone_no, password}."""
    ident = beli_id.strip()
    if is_phone_identifier(ident):
        return {"phone_no": ident, "password": password}
    return {"email": ident, "password": password}


def results_of(data) -> list:
    """Unwrap Beli's response envelopes into arrays.

    Handles: raw arrays, {results: [...]}, and category-keyed objects like
    {"Restaurants": [...]} from /api/get-bookmark/.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return data["results"]
        if isinstance(data.get("Restaurants"), list):
            return data["Restaurants"]
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def _jwt_exp_ms(token: str) -> float | None:
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        return float(exp) * 1000 if isinstance(exp, (int, float)) else None
    except Exception:
        return None


def _read_json_response(resp) -> object:
    # some Beli writes (e.g. add-bookmark) answer 200/201 with an empty body
    raw = resp.read().decode("utf-8", errors="replace").strip()
    return json.loads(raw) if raw else None


class BeliClient:
    """Authenticated Beli API access for a single Beli account."""

    def __init__(self, beli_id: str, password: str):
        self.beli_id = beli_id
        self.password = password
        self._lock = threading.Lock()
        self._last_call_at = 0.0
        self._access: str | None = None
        self._refresh: str | None = None
        self._access_exp_ms = 0.0

    # -- internals ---------------------------------------------------------
    def _pace(self) -> None:
        with self._lock:
            wait = MIN_GAP_S - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()

    def _request(
        self,
        host: str,
        path: str,
        method: str = "GET",
        body: object = None,
        access_token: str | None = None,
    ) -> object:
        self._pace()
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(host + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", random.choice(USER_AGENTS))
        req.add_header("Origin", ORIGIN)
        if access_token:
            req.add_header("Authorization", f"Bearer {access_token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _read_json_response(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise BeliUnauthorized("unauthorized", status=401)
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            raise BeliError(f"Beli {method} {path} -> {e.code} {detail}", status=e.code)

    def _onboard(self, path: str, method: str = "GET", body: object = None) -> object:
        return self._request(ONBOARD_HOST, path, method, body)

    def ensure_access_token(self) -> str:
        now_ms = time.time() * 1000
        if self._access and self._access_exp_ms - now_ms > 60_000:
            return self._access
        if self._refresh:
            try:
                data = self._onboard(
                    "/api/token/refresh/", "POST", {"refresh": self._refresh}
                )
                access = (data or {}).get("access") if isinstance(data, dict) else None
                if access:
                    self._access = access
                    self._access_exp_ms = _jwt_exp_ms(access) or (now_ms + 20 * 60_000)
                    return access
            except BeliError:
                pass  # refresh died; fall through to full login
            self._access = self._refresh = None
        data = self._onboard("/api/token/", "POST", login_body(self.beli_id, self.password))
        if not isinstance(data, dict) or not data.get("access"):
            raise BeliError("Beli login failed: no access token returned")
        self._access = data["access"]
        self._refresh = data.get("refresh")
        self._access_exp_ms = _jwt_exp_ms(self._access) or (now_ms + 20 * 60_000)
        return self._access

    # -- public API ---------------------------------------------------------
    def api(self, path: str, method: str = "GET", body: object = None) -> object:
        """Authenticated request against the main API host (no re-auth)."""
        return self._request(API_HOST, path, method, body, self.ensure_access_token())

    def api_with_reauth(self, path: str, method: str = "GET", body: object = None) -> object:
        """Same as api() but retries once after a full re-login on 401."""
        try:
            return self.api(path, method, body)
        except BeliUnauthorized:
            self._access = self._refresh = None
            return self.api(path, method, body)

    @staticmethod
    def probe_credentials(beli_id: str, password: str) -> dict:
        """Validate a Beli login without keeping any state. Returns the user object."""
        client = BeliClient(beli_id, password)
        me = client.api_with_reauth("/api/user/logged-in/")
        obj = results_of(me)
        user = obj[0] if obj else (me if isinstance(me, dict) else {})
        if not isinstance(user, dict) or not (user.get("uuid") or user.get("id")):
            raise BeliError("Beli login succeeded but no user record was returned")
        return user
