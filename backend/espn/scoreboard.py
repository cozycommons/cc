"""Public ESPN scoreboard client (no auth) — the schedule fallback.

ESPN's public site API publishes the NBA schedule without any
credentials::

    GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD

Two ``dates`` forms work (verified live, Oct 2026): a single day
(``YYYYMMDD``) and a whole month (``YYYYMM``, with ``limit=1000`` —
the default response caps at 100 events and a full month runs ~155).
The hyphenated range form (``YYYYMMDD-YYYYMMDD``) is rejected with
HTTP 400, so spans are fetched month by month. Event competitor ids
live in ESPN's canonical NBA team-id space — the same space as
fantasy ``proTeamId`` (CHA 30, WAS 27, CLE 5, MIN 16, BOS 2, CHI 4,
MIA 14, DAL 6, ...). ``PRO_TEAM_ABBR`` below is the backend's single
id -> abbreviation map for that space.

This client exists because the fantasy league payload does not
always carry its ``proGamesByScoringPeriod`` schedule block (in
preseason it carries none at all). The lineup runner prefers that
block when it is present and falls back to this scoreboard when it
is absent — see ``espn/lineup.py``. Each event also carries a season
type (1 = preseason, 2 = regular season, 3 = postseason), which is
how the first regular-season date — the anchor for scoring-period
1 — is found without the fantasy payload's help.

Defensive like the fantasy client: one attempt per fetch (no retry
hammering), a hard timeout, and every failure mapped onto EspnError.
There is no auth here, so nothing raises EspnAuthError.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .espn_client import EspnError, USER_AGENT

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)

PRESEASON = 1
REGULAR_SEASON = 2
POSTSEASON = 3

_ET = ZoneInfo("America/New_York")
_TIMEOUT_S = 15

# ESPN pro team id -> abbreviation, in the canonical NBA team-id
# space this module documents (the space scoreboard competitor ids
# and fantasy ``proTeamId`` share). This is the backend's single
# source of truth for pro-team labels: display code (espn/waivers.py,
# espn/roster_edits.py) reads the map from here instead of keeping
# its own copy. Waivers once kept its own, with 26/27/28 rotated
# (TOR/UTA/WAS), which mislabeled Utah players as Toronto's in the
# waiver digest. Anchors verified against live fantasy roster
# payloads (Oct 2026): 26 = Utah (Mo Bamba, Lauri Markkanen, Keyonte
# George), 27 = Washington (Bilal Coulibaly), 28 = Toronto (Scottie
# Barnes).
PRO_TEAM_ABBR = {
    1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC",
    13: "LAL", 14: "MIA", 15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK",
    19: "ORL", 20: "PHI", 21: "PHX", 22: "POR", 23: "SAC", 24: "SAS",
    25: "OKC", 26: "UTA", 27: "WAS", 28: "TOR", 29: "MEM", 30: "CHA",
}


def _event_date(event: dict) -> _date | None:
    """The event's calendar date in America/New_York, or None.

    A 7:30pm ET tip-off is already the next day in UTC, so the
    conversion matters — the same rule the fantasy pro-games block
    uses for its game timestamps.
    """
    raw = event.get("date")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_ET).date()


def _competitor_team_id(competitor: dict) -> int | None:
    raw = competitor.get("id")
    if raw is None:
        team = competitor.get("team")
        if isinstance(team, dict):
            raw = team.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _event_tipoff(event: dict):
    """The event's tip-off as an aware datetime, or None."""
    raw = event.get("date")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def parse_scoreboard(payload) -> dict:
    """Parse a scoreboard payload into per-date schedule buckets.

    Returns ``{date: {"teams": set[int], "season_types": set[int],
    "tipoffs": {team_id: datetime}}}`` — tipoffs are the earliest
    tip-off per team that day (the lineup runner's per-player lock
    source when the fantasy payload has no pro-games block).
    Malformed events are skipped rather than guessed at.
    """
    days: dict[_date, dict] = {}
    if not isinstance(payload, dict):
        return days
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        day = _event_date(event)
        if day is None:
            continue
        bucket = days.setdefault(
            day, {"teams": set(), "season_types": set(), "tipoffs": {}}
        )
        season = event.get("season")
        if isinstance(season, dict):
            stype = season.get("type")
            if isinstance(stype, int):
                bucket["season_types"].add(stype)
        tipoff = _event_tipoff(event)
        for competition in event.get("competitions") or []:
            if not isinstance(competition, dict):
                continue
            for competitor in competition.get("competitors") or []:
                if not isinstance(competitor, dict):
                    continue
                team_id = _competitor_team_id(competitor)
                if team_id is not None:
                    bucket["teams"].add(team_id)
                    if tipoff is not None and (
                        team_id not in bucket["tipoffs"]
                        or tipoff < bucket["tipoffs"][team_id]
                    ):
                        bucket["tipoffs"][team_id] = tipoff
    return days


class ScoreboardClient:
    """Fetches and caches scoreboard days for one lineup run.

    Stateless across runs (construct one per run); within a run,
    days and months already fetched are served from the cache and
    never re-requested.
    """

    def __init__(self):
        self._days: dict[_date, dict] = {}
        self._fetched_days: set[_date] = set()
        self._fetched_months: set[tuple[int, int]] = set()

    # -- wire ---------------------------------------------------------------
    def _fetch(self, params: dict) -> dict:
        """One GET round-trip; returns the parsed per-date buckets."""
        url = SCOREBOARD_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            raise EspnError(
                f"ESPN scoreboard -> {e.code} {detail}", status=e.code
            ) from e
        except urllib.error.URLError as e:
            raise EspnError(f"ESPN scoreboard: network error {e}") from e
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise EspnError(f"ESPN scoreboard returned non-JSON: {e}") from e
        return parse_scoreboard(payload)

    def _fetch_day(self, day: _date) -> None:
        parsed = self._fetch({"dates": day.strftime("%Y%m%d")})
        self._fetched_days.add(day)
        for d, bucket in parsed.items():
            self._days.setdefault(d, bucket)
        self._days.setdefault(
            day, {"teams": set(), "season_types": set(), "tipoffs": {}}
        )

    def _fetch_month(self, year: int, month: int) -> None:
        parsed = self._fetch(
            {"dates": f"{year:04d}{month:02d}", "limit": 1000}
        )
        self._fetched_months.add((year, month))
        for d, bucket in parsed.items():
            self._days[d] = bucket

    # -- public API -----------------------------------------------------------
    def get_day(self, day: _date) -> dict:
        """{"teams": set[int], "season_types": set[int],
        "tipoffs": {team_id: datetime}} for one date."""
        if day in self._days:
            return self._days[day]
        if (day.year, day.month) in self._fetched_months or day in self._fetched_days:
            # Covered by an earlier fetch and absent from it: a real
            # no-games day, not a missing fetch.
            return {"teams": set(), "season_types": set(), "tipoffs": {}}
        self._fetch_day(day)
        return self._days[day]

    def teams_on(self, day: _date) -> set:
        """Pro team ids with a game on the date (any season type)."""
        return set(self.get_day(day)["teams"])

    def team_tipoffs_on(self, day: _date) -> dict:
        """{pro team id: earliest tip-off datetime} for the date."""
        return dict(self.get_day(day).get("tipoffs") or {})

    def first_regular_season_date(self, start: _date, end: _date):
        """Earliest date in the span with a regular-season game, or None.

        Fetches each overlapped month once (October alone settles the
        usual season-start window) and scans forward — dark days with
        no games are simply skipped.
        """
        day = start
        while day <= end:
            key = (day.year, day.month)
            if key not in self._fetched_months:
                self._fetch_month(*key)
            if REGULAR_SEASON in self.get_day(day)["season_types"]:
                return day
            day += timedelta(days=1)
        return None
