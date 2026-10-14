"""ESPN Fantasy API client (unofficial).

ESPN Fantasy has no public API. Everything here runs on the unofficial
v3 API the ESPN web app itself uses
(``https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba`` for reads,
``https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba`` for the one
write this module performs), hard-coded to basketball (game code
``fba``). It is undocumented, unsupported, and may change without
notice — this client fails loudly on unexpected shapes rather than
guessing.

Endpoints:
  - League: ``GET /seasons/{season}/segments/0/leagues/{league_id}``
    Views are passed as repeated query params
    (``?view=mSettings&view=mTeam&...``) and the response is one merged
    JSON object. ``season`` is the ENDING year (the 2026-27 season is
    season 2027).
  - Players: ``GET /seasons/{season}/players?view=kona_player_info``
    with an ``X-Fantasy-Filter`` header carrying a JSON filter/sort
    document; the response is a bare JSON list of player entries.
    The filter can also scope the returned stat splits to one
    scoring period (``filterStatsForScoringPeriodIds``) — that is
    where per-day projections live when the league payload's roster
    entries carry none (see :meth:`EspnClient.get_players_for_period`).
  - Lineup moves (v2): ``POST .../leagues/{league_id}/transactions/``
    on the write host with a ``ROSTER`` transaction whose items are
    ``LINEUP`` moves (playerId, fromLineupSlotId, toLineupSlotId).
    That is the ONLY write: there are deliberately no add / drop /
    trade / waiver methods anywhere in this module.

Auth is cookie-based: the user's ``espn_s2`` and ``SWID`` cookies are
sent as a single ``Cookie`` header (``SWID`` is passed through verbatim —
it contains braces). There is no refresh flow: when the cookies expire
ESPN answers 401/403, or a 200 whose body is an HTML login page instead
of JSON. Both raise EspnAuthError — the user must re-onboard with fresh
espn_s2/SWID cookies, and the client never returns the HTML as data.

One EspnClient instance = one ESPN account / one league. Request pacing
is per-instance (the backend is multi-tenant; nothing is shared across
accounts). Cookies are never logged.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
WRITE_API_BASE = "https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba"
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
    """Authenticated ESPN Fantasy access for a single league.

    Reads plus exactly one write (lineup-move transactions); see the
    module docstring.
    """

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

    def _post(self, url: str, body: dict, what: str = "ESPN write"):
        """One paced POST round-trip; returns the parsed JSON body.

        Same failure mapping as :meth:`_get`: 401/403 and HTML-login
        200s are auth failures (re-onboard), other HTTP errors carry
        their status, and non-JSON bodies are never returned as data.
        """
        self._pace()
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        headers = self._headers({"Content-Type": "application/json"})
        for k, v in headers.items():
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
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            lowered = text.lower()
            if text.startswith("<") or "<html" in lowered or "login" in lowered:
                raise EspnAuthError(f"{what}: {AUTH_EXPIRED_MESSAGE}") from e
            raise EspnError(f"ESPN returned non-JSON: {e}") from e

    # -- public read API ----------------------------------------------------
    def league_url(self) -> str:
        return (
            f"{API_BASE}/seasons/{self.season}/segments/0"
            f"/leagues/{self.league_id}"
        )

    def get_league(self, views: list[str], scoring_period_id: int | None = None) -> dict:
        """League payload merged across the requested views.

        ``views`` are sent as repeated ``view`` query params; ESPN
        returns one merged JSON object for all of them. When
        ``scoring_period_id`` is given it rides along as a query param
        and ESPN scopes the roster to that day — that is how lineups
        for future days are read (and verified) in advance.
        """
        url = self.league_url()
        params = [("view", view) for view in views]
        if scoring_period_id is not None:
            params.append(("scoringPeriodId", scoring_period_id))
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = self._get(url, what="ESPN league")
        if not isinstance(data, dict):
            raise EspnError("ESPN league: unexpected response (expected object)")
        return data

    def _fetch_players(self, players_filter: dict) -> list:
        """One kona_player_info fetch with the given filter document."""
        url = (
            f"{API_BASE}/seasons/{self.season}/players"
            "?view=kona_player_info"
        )
        data = self._get(
            url,
            headers={"X-Fantasy-Filter": json.dumps(players_filter)},
            what="ESPN players",
        )
        if not isinstance(data, list):
            raise EspnError("ESPN players: unexpected response (expected list)")
        return data

    def get_players(self, limit: int = 300) -> list:
        """Player entries for the season, sorted by percent owned (desc).

        The filter/sort document travels in the ``X-Fantasy-Filter``
        header; the response is a bare JSON list.
        """
        return self._fetch_players(
            {
                "players": {
                    "limit": limit,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                }
            }
        )

    def get_players_for_period(
        self, scoring_period_id: int, limit: int = 1000
    ) -> list:
        """Kona player entries with stat splits for ONE scoring period.

        ``filterStatsForScoringPeriodIds`` scopes each player's
        ``stats`` to the requested day, so projected splits
        (statSourceId 1) come back keyed by that scoringPeriodId.
        This is the lineup schedule gate's projection source when the
        period-scoped roster payload carries no per-period projected
        splits (the preseason shape: ESPN publishes none there). The
        gate only needs pro-team coverage — one projected player per
        team registers the team — so a generous ownership-sorted limit
        suffices: every team's most-owned players sit far inside it.
        """
        return self._fetch_players(
            {
                "players": {
                    "filterStatsForScoringPeriodIds": {
                        "value": [int(scoring_period_id)]
                    },
                    "limit": limit,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                }
            }
        )

    # -- the one write: lineup moves ---------------------------------------
    def transactions_url(self) -> str:
        return (
            f"{WRITE_API_BASE}/seasons/{self.season}/segments/0"
            f"/leagues/{self.league_id}/transactions/"
        )

    def post_lineup_transaction(
        self, member_id: str, team_id: int, scoring_period_id: int, items: list
    ) -> dict:
        """Submit one ROSTER transaction made only of LINEUP moves.

        ``items`` are dicts with ``playerId``, ``fromLineupSlotId`` and
        ``toLineupSlotId``; the ``type: "LINEUP"`` marker is stamped
        here so callers cannot smuggle in any other move type. This is
        the module's only write — adds, drops, trades and waiver claims
        are out of scope by design and have no code path.

        Returns ESPN's transaction response. Raises EspnAuthError when
        the cookies are dead (callers record that as a conflict-level
        event and stop) and EspnError on any other failure.
        """
        stamped = []
        for item in items:
            stamped.append(
                {
                    "playerId": item["playerId"],
                    "type": "LINEUP",
                    "fromLineupSlotId": item["fromLineupSlotId"],
                    "toLineupSlotId": item["toLineupSlotId"],
                }
            )
        body = {
            "isLeagueManager": False,
            "memberId": member_id,
            "scoringPeriodId": scoring_period_id,
            "teamId": team_id,
            "type": "ROSTER",
            "items": stamped,
        }
        data = self._post(
            self.transactions_url(), body, what="ESPN lineup transaction"
        )
        if not isinstance(data, dict):
            raise EspnError(
                "ESPN lineup transaction: unexpected response (expected object)"
            )
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
