"""Minimal ESPN Fantasy API client (unofficial, read-only).

ESPN Fantasy has no public API. Everything here runs on the unofficial
v3 read API the ESPN web app itself uses
(``https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba``), hard-coded
to basketball (game code ``fba``). It is undocumented, unsupported, and
may change without notice — this client fails loudly on unexpected
shapes rather than guessing.

Endpoints:
  - League: ``GET /seasons/{season}/segments/0/leagues/{league_id}``
    Views are passed as repeated query params
    (``?view=mSettings&view=mTeam&...``) and the response is one merged
    JSON object. ``season`` is the ENDING year (the 2026-27 season is
    season 2027).
  - Players: ``GET /seasons/{season}/players?view=kona_player_info``
    with an ``X-Fantasy-Filter`` header carrying a JSON filter/sort
    document; the response is a bare JSON list of player entries.

Auth is cookie-based: the user's ``espn_s2`` and ``SWID`` cookies are
sent as a single ``Cookie`` header (``SWID`` is passed through verbatim —
it contains braces). There is no refresh flow: when the cookies expire
ESPN answers 401/403, or a 200 whose body is an HTML login page instead
of JSON. Both raise EspnAuthError — the user must re-onboard with fresh
espn_s2/SWID cookies, and the client never returns the HTML as data.

One EspnClient instance = one ESPN account / one league. Request pacing
is per-instance (the backend is multi-tenant; nothing is shared across
accounts). Cookies are never logged.

Read-only: this client exposes no write methods at all.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MIN_GAP_S = 1.0

AUTH_EXPIRED_MESSAGE = (
    "ESPN cookies expired or were rejected; re-onboard with fresh "
    "espn_s2/SWID cookies to continue"
)


class EspnError(Exception):
    """Non-auth ESPN API failure (carries HTTP status when known)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class EspnAuthError(EspnError):
    """The stored cookies are expired/rejected — the user must re-onboard."""


class EspnClient:
    """Authenticated ESPN Fantasy read access for a single league."""

    def __init__(self, espn_s2: str, swid: str, league_id: int, season: int):
        self._espn_s2 = (espn_s2 or "").strip()
        self._swid = (swid or "").strip()
        self.league_id = league_id
        self.season = season
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    # -- internals ---------------------------------------------------------
    def _pace(self) -> None:
        with self._lock:
            wait = MIN_GAP_S - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Cookie": f"espn_s2={self._espn_s2}; SWID={self._swid}",
        }
        if extra:
            headers.update(extra)
        return headers

    def _get(self, url: str, headers: dict | None = None, what: str = "ESPN request"):
        """One paced GET round-trip; returns the parsed JSON body.

        Maps every failure mode onto EspnError / EspnAuthError: 401/403
        and HTML-login 200s are auth failures (re-onboard), other HTTP
        errors carry their status, and non-JSON bodies are never
        returned as data.
        """
        self._pace()
        req = urllib.request.Request(url, method="GET")
        for k, v in self._headers(headers).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise EspnAuthError(
                    f"{what} -> {e.code}: {AUTH_EXPIRED_MESSAGE}", status=e.code
                ) from e
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            raise EspnError(f"{what} -> {e.code} {detail}", status=e.code) from e
        except urllib.error.URLError as e:
            raise EspnError(f"{what}: network error {e}") from e
        text = raw.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            lowered = text.lower()
            if (
                text.startswith("<")
                or "<html" in lowered
                or "login" in lowered
            ):
                raise EspnAuthError(
                    f"{what}: {AUTH_EXPIRED_MESSAGE}"
                ) from e
            raise EspnError(f"ESPN returned non-JSON: {e}") from e

    # -- public read API ----------------------------------------------------
    def league_url(self) -> str:
        return (
            f"{API_BASE}/seasons/{self.season}/segments/0"
            f"/leagues/{self.league_id}"
        )

    def get_league(self, views: list[str]) -> dict:
        """League payload merged across the requested views.

        ``views`` are sent as repeated ``view`` query params; ESPN
        returns one merged JSON object for all of them.
        """
        url = self.league_url()
        if views:
            url += "?" + urllib.parse.urlencode(
                [("view", view) for view in views]
            )
        data = self._get(url, what="ESPN league")
        if not isinstance(data, dict):
            raise EspnError("ESPN league: unexpected response (expected object)")
        return data

    def get_players(self, limit: int = 300) -> list:
        """Player entries for the season, sorted by percent owned (desc).

        The filter/sort document travels in the ``X-Fantasy-Filter``
        header; the response is a bare JSON list.
        """
        url = (
            f"{API_BASE}/seasons/{self.season}/players"
            "?view=kona_player_info"
        )
        fantasy_filter = {
            "players": {
                "limit": limit,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            }
        }
        data = self._get(
            url,
            headers={"X-Fantasy-Filter": json.dumps(fantasy_filter)},
            what="ESPN players",
        )
        if not isinstance(data, list):
            raise EspnError("ESPN players: unexpected response (expected list)")
        return data

    # -- onboarding (static; no account state) ------------------------------
    @staticmethod
    def probe(espn_s2, swid, league_id, season) -> dict:
        """Validate cookies against a league before storing them.

        Constructs a client and returns ``get_league(["mSettings",
        "mTeam"])``; raises EspnAuthError / EspnError if the cookies
        don't work, so only working credentials are ever stored.
        """
        client = EspnClient(espn_s2, swid, league_id, season)
        return client.get_league(["mSettings", "mTeam"])
