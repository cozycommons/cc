"""Tests for the ESPN lineup schedule fallback (public scoreboard).

Two layers:

- ScoreboardClient wire tests: the public ESPN scoreboard payload
  (stubbed urlopen; no network) parses into per-date team sets in
  ESPN's canonical NBA id space — the same space as fantasy
  proTeamId (CHA 30, WSH 27, CLE 5, MIN 16, BOS 2, CHI 4, MIA 14,
  DAL 6) — bucketed by America/New_York date, with preseason vs
  regular-season events distinguished.

- Runner tests: when the fantasy league payload has NO
  proGamesByScoringPeriod block (the live preseason shape), runs
  resolve dates and playing sets from the scoreboard, gated against
  the period-scoped payload's projected teams. Covers the happy
  path, anchor calibration, gate aborts, block-over-scoreboard
  precedence, the no-date paths, and dry-run.
"""

import copy
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from espn import lineup, scoreboard
from espn.espn_client import EspnAuthError, EspnError
from espn.scoreboard import ScoreboardClient

PG, SG, SF, PF, C, G, F, UTIL, BE, IR = 0, 1, 2, 3, 4, 5, 6, 11, 12, 13
STARTING = {PG, SG, SF, PF, C, G, F, UTIL}
SWID = "{SWID-1}"
ACCOUNT = {
    "id": "acc-1",
    "label": "warner",
    "league_id": 999,
    "season": 2027,
    "espn_s2": "s2-secret",
    "swid": SWID,
    "lineup_automation_enabled": False,
}

_ET = ZoneInfo("America/New_York")

# The Mon 2026-10-26 fixture slate, in ESPN's canonical NBA ids
# (verified live: CHA 30, WSH 27, CLE 5, MIN 16, BOS 2, CHI 4,
# MIA 14, DAL 6).
OCT26 = date(2026, 10, 26)
OCT26_SLATE = {2, 4, 5, 6, 14, 16, 27, 30}
SEASON_START = date(2026, 10, 21)  # first regular-season date (fixture)


# --- scoreboard wire fixtures ----------------------------------------------------


def _sb_event(eid, utc_iso, season_type, home_id, away_id):
    return {
        "id": str(eid),
        "date": utc_iso,
        "name": f"Team {away_id} at Team {home_id}",
        "season": {"year": 2026, "type": season_type},
        "competitions": [
            {
                "competitors": [
                    {
                        "id": str(home_id),
                        "homeAway": "home",
                        "team": {"id": str(home_id)},
                    },
                    {
                        "id": str(away_id),
                        "homeAway": "away",
                        "team": {"id": str(away_id)},
                    },
                ]
            }
        ],
    }


# (utc_iso, season_type, home, away). Ids are the verified canonical
# ones; the 2026-10-27T01:30Z game is Oct 26 in ET — it pins the
# ET bucketing (its UTC date is the 27th).
MASTER_EVENTS = [
    _sb_event(1, "2026-10-14T23:00Z", 1, 27, 30),   # preseason WSH/CHA
    _sb_event(2, "2026-10-16T23:30Z", 1, 2, 4),     # preseason BOS/CHI
    _sb_event(3, "2026-10-21T23:00Z", 2, 16, 5),    # regular MIN/CLE
    _sb_event(4, "2026-10-22T00:30Z", 2, 4, 2),     # regular, ET Oct 21
    _sb_event(5, "2026-10-23T00:00Z", 2, 6, 14),    # regular, ET Oct 22
    _sb_event(6, "2026-10-27T01:30Z", 2, 30, 27),   # regular, ET Oct 26
]


def _et_date(event):
    moment = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
    return moment.astimezone(_ET).date()


class FakeHTTPResponse:
    def __init__(self, payload):
        if isinstance(payload, (bytes, str)):
            self._raw = (
                payload.encode("utf-8") if isinstance(payload, str) else payload
            )
        else:
            self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture()
def sb_server(monkeypatch):
    """Serves MASTER_EVENTS for whatever `dates` span is requested.

    Handles both live forms: a single day (YYYYMMDD) and a whole
    month (YYYYMM, with the limit parameter the client sends).
    """
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        parsed = urllib.parse.urlparse(req.full_url)
        assert parsed.netloc == "site.api.espn.com"
        assert parsed.path.endswith("/sports/basketball/nba/scoreboard")
        query = urllib.parse.parse_qs(parsed.query)
        dates = query["dates"][0]
        if len(dates) == 6:  # month form
            year, month = int(dates[:4]), int(dates[4:])
            assert query.get("limit") == ["1000"]
            events = [
                e for e in MASTER_EVENTS
                if (_et_date(e).year, _et_date(e).month) == (year, month)
            ]
        else:  # single day
            day = datetime.strptime(dates, "%Y%m%d").date()
            events = [e for e in MASTER_EVENTS if _et_date(e) == day]
        return FakeHTTPResponse({"events": events})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


def test_scoreboard_single_day_parse_and_id_alignment(sb_server):
    client = ScoreboardClient()
    day = client.get_day(date(2026, 10, 14))
    # CHA 30 / WSH 27: scoreboard ids are fantasy proTeamIds verbatim
    assert day["teams"] == {30, 27}
    assert day["season_types"] == {1}  # preseason
    assert "dates=20261014" in sb_server[0]

    day = client.get_day(date(2026, 10, 21))
    assert day["teams"] == {16, 5, 4, 2}  # MIN, CLE, CHI, BOS
    assert day["season_types"] == {2}  # regular season


def test_scoreboard_month_fetch_and_et_bucketing(sb_server):
    client = ScoreboardClient()
    found = client.first_regular_season_date(
        date(2026, 10, 1), date(2026, 11, 30)
    )
    assert found == date(2026, 10, 21)
    # one month-form request settled the whole window
    assert len(sb_server) == 1
    assert "dates=202610" in sb_server[0]
    # the 2026-10-27T01:30Z tip-off is an Oct 26 ET game, served from
    # the month cache — no second request
    assert client.teams_on(date(2026, 10, 26)) == {30, 27}
    assert len(sb_server) == 1
    # a day in the fetched month with no events is a real no-games
    # day, not a fetch failure — and also costs no request
    assert client.teams_on(date(2026, 10, 27)) == set()
    assert len(sb_server) == 1


def test_scoreboard_team_tipoffs(sb_server):
    client = ScoreboardClient()
    tipoffs = client.team_tipoffs_on(date(2026, 10, 21))
    # event 3 tips 2026-10-21T23:00Z (MIN 16 / CLE 5); event 4 tips
    # 2026-10-22T00:30Z but buckets to Oct 21 in ET (CHI 4 / BOS 2)
    assert tipoffs == {
        16: datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc),
        5: datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc),
        4: datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc),
        2: datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc),
    }
    # a no-games day has no tip-offs
    assert client.team_tipoffs_on(date(2026, 10, 27)) == {}


def test_first_regular_season_date_skips_preseason(sb_server):
    client = ScoreboardClient()
    found = client.first_regular_season_date(
        date(2026, 10, 1), date(2026, 11, 30)
    )
    assert found == date(2026, 10, 21)
    # a window covering only preseason days finds nothing
    assert (
        client.first_regular_season_date(date(2026, 10, 1), date(2026, 10, 18))
        is None
    )


def test_scoreboard_errors_are_espn_errors(monkeypatch):
    def fail(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 503, "error", {}, io.BytesIO(b"down")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(EspnError) as excinfo:
        ScoreboardClient().get_day(date(2026, 10, 26))
    assert excinfo.value.status == 503

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: FakeHTTPResponse("nope")
    )
    with pytest.raises(EspnError):
        ScoreboardClient().get_day(date(2026, 10, 26))


# --- runner fakes ------------------------------------------------------------------


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None

    def _base(self):
        return self._rows if self._rows is not None else list(self._store)

    def insert(self, row):
        row = dict(row)
        row["id"] = f"run-{len(self._store) + 1}"
        row["created_at"] = f"2026-10-15T00:00:{len(self._store):02d}+00:00"
        self._store.append(row)
        self._rows = [row]
        return self

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in self._base() if r.get(k) == v]
        return self

    def order(self, column, desc=False):
        self._rows = sorted(self._base(), key=lambda r: r.get(column), reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._base()[:n]
        return self

    def execute(self):
        class R:
            data = self._rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []

    def table(self, name):
        assert name == "espn_lineup_runs"
        return FakeTable(self._store)


class StatefulClient:
    """Same payload for every scoping (projections are period-keyed
    inside it); mutates roster slots when a transaction is posted."""

    def __init__(self, payload):
        self.payload = payload
        self.posts = []

    def get_league(self, views, scoring_period_id=None):
        return copy.deepcopy(self.payload)

    def post_lineup_transaction(self, member_id, team_id, scoring_period_id, items):
        self.posts.append(
            {
                "member_id": member_id,
                "team_id": team_id,
                "scoring_period_id": scoring_period_id,
                "items": items,
            }
        )
        entries = self.payload["teams"][0]["roster"]["entries"]
        by_id = {e["playerId"]: e for e in entries}
        for item in items:
            by_id[item["playerId"]]["lineupSlotId"] = item["toLineupSlotId"]
        return {"status": "EXECUTED"}


class FakeScoreboard:
    """Duck-typed ScoreboardClient over a {date: teams} dict."""

    def __init__(self, days, season_start=SEASON_START):
        self.days = days
        self.season_start = season_start
        self.calls = []

    def teams_on(self, day):
        self.calls.append(("teams_on", day))
        return set(self.days.get(day, set()))

    def first_regular_season_date(self, start, end):
        self.calls.append(("first_regular_season_date", start, end))
        return self.season_start


def _fb_player(pid, team, eligible, value=None, status="ACTIVE", proj_periods=()):
    stats = [
        {
            "statSourceId": 1,  # projected split for that period
            "statSplitTypeId": 5,
            "scoringPeriodId": pp,
            "appliedTotal": float(value if value is not None else 20),
        }
        for pp in proj_periods
    ]
    return {
        "id": pid,
        "fullName": f"Player {pid}",
        "proTeamId": team,
        "defaultPositionId": eligible[0],
        "eligibleSlots": list(eligible),
        "injuryStatus": status,
        "stats": stats,
    }


def _entry(pid, slot, player):
    return {"playerId": pid, "lineupSlotId": slot, "playerPoolEntry": {"player": player}}


def _no_block_payload(entries, current=1, first=1):
    """A league payload with NO proGamesByScoringPeriod (preseason shape)."""
    status = {"firstScoringPeriod": first}
    if current is not None:
        status["currentScoringPeriod"] = current
    return {
        "id": 999,
        "seasonId": 2027,
        "status": status,
        "settings": {
            "rosterSettings": {
                "lineupSlotCounts": {
                    "0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                    "5": 1, "6": 1, "11": 3, "12": 3, "13": 1,
                }
            },
            "scoringSettings": {"scoringItems": [{"statId": 0, "points": 1.0}]},
        },
        "teams": [{"id": 7, "owners": [SWID], "roster": {"entries": entries}}],
    }


def _oct26_roster(proj_period):
    """10 starters on Oct-26-slate teams (all projected for
    proj_period), plus bench/IR players on teams that do not play."""
    slate = [
        (101, BE, 2, [PG, G, UTIL, BE], 30),
        (102, BE, 4, [SG, UTIL, BE], 28),
        (103, BE, 5, [SF, F, UTIL, BE], 27),
        (104, BE, 16, [PF, F, UTIL, BE], 26),
        (105, BE, 14, [C, UTIL, BE], 29),
        (106, UTIL, 6, [PG, SG, G, UTIL, BE], 24),
        (107, UTIL, 30, [SF, PF, F, UTIL, BE], 23),
        (108, UTIL, 27, [UTIL, BE], 20),
        (109, BE, 2, [C, UTIL, BE], 19),
        (110, BE, 4, [SG, G, UTIL, BE], 18),
    ]
    entries = [
        _entry(pid, slot, _fb_player(pid, team, elig, val, proj_periods=(proj_period,)))
        for pid, slot, team, elig, val in slate
    ]
    entries += [
        _entry(111, BE, _fb_player(111, 1, [PG, G, UTIL, BE])),
        _entry(112, BE, _fb_player(112, 3, [SF, F, UTIL, BE])),
        _entry(113, BE, _fb_player(113, 9, [C, UTIL, BE])),
        _entry(114, IR, _fb_player(114, 9, [C, UTIL, BE, IR], status="OUT")),
    ]
    return entries


# --- runner: date resolution through the fallback ---------------------------------


def test_date_run_via_scoreboard_happy_path():
    db = FakeSupabase()
    payload = _no_block_payload(_oct26_roster(6))
    client = StatefulClient(payload)
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 6  # Oct 21 = period 1, +5 days
    schedule = run["plan"]["schedule"]
    assert schedule["source"] == "scoreboard"
    assert schedule["target_date"] == "2026-10-26"
    assert schedule["season_start_date"] == "2026-10-21"
    assert schedule["anchor_period"] == 6
    assert schedule["candidate_offset"] == 0
    assert schedule["gate"]["verdict"] == "match"
    # every slate player is scheduled (canonical ids line up with
    # fantasy proTeamIds); the off-slate players are not
    plan = {p["player_id"]: p for p in run["plan"]["players"]}
    for pid in range(101, 111):
        assert plan[pid]["scheduled"] is True
        assert plan[pid]["to_slot"] in STARTING
    for pid in (111, 112, 113, 114):
        assert plan[pid]["scheduled"] is False
    (post,) = client.posts
    assert post["scoring_period_id"] == 6
    # the window lookup used the season-start window for season 2027
    assert sb.calls[0] == (
        "first_regular_season_date", date(2026, 10, 1), date(2026, 11, 30)
    )


def test_date_run_calibrates_when_anchor_is_off_by_one():
    # ESPN's period 1 is Oct 20 here — one day BEFORE the scoreboard's
    # first regular-season date — so the raw anchor lands on period 6
    # for Oct 26 while the projections live on period 7.
    db = FakeSupabase()
    payload = _no_block_payload(_oct26_roster(7))
    client = StatefulClient(payload)
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 7
    schedule = run["plan"]["schedule"]
    assert schedule["anchor_period"] == 6
    assert schedule["candidate_offset"] == 1
    assert [t["period"] for t in schedule["candidates_tried"]] == [6, 5, 7]
    assert [t["passed"] for t in schedule["candidates_tried"]] == [False, False, True]
    (post,) = client.posts
    assert post["scoring_period_id"] == 7


def test_date_run_gate_abort_records_error_and_submits_nothing():
    # Projections exist for the candidate periods but for a disjoint
    # set of teams: nothing near the anchor matches the slate.
    entries = [
        _entry(201, BE, _fb_player(201, 11, [PG, G, UTIL, BE], 25, proj_periods=(3, 4, 5, 6, 7, 8, 9))),
        _entry(202, BE, _fb_player(202, 12, [SG, UTIL, BE], 24, proj_periods=(3, 4, 5, 6, 7, 8, 9))),
        _entry(203, BE, _fb_player(203, 13, [C, UTIL, BE], 23, proj_periods=(3, 4, 5, 6, 7, 8, 9))),
        _entry(204, BE, _fb_player(204, 1, [UTIL, BE])),
    ]
    db = FakeSupabase()
    client = StatefulClient(_no_block_payload(entries))
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "error"
    assert "schedule gate" in run["error"]
    assert run["plan"] is None
    assert client.posts == []
    assert len(db._store) == 1  # the failed run is still recorded


def test_date_run_dry_run_via_scoreboard_submits_nothing():
    db = FakeSupabase()
    client = StatefulClient(_no_block_payload(_oct26_roster(6)))
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, date="2026-10-26", dry_run=True, scoreboard=sb
    )
    assert run["status"] == "dry_run"
    assert run["scoring_period_id"] == 6
    assert run["plan"]["schedule"]["source"] == "scoreboard"
    assert run["plan"]["moves"]
    assert client.posts == []


# --- runner: precedence and the other trigger paths --------------------------------


def _games(*team_ids):
    games = []
    ids = list(team_ids)
    for i in range(0, len(ids), 2):
        game = {"homeProTeamId": ids[i]}
        if i + 1 < len(ids):
            game["awayProTeamId"] = ids[i + 1]
        games.append(game)
    return games


def test_block_takes_precedence_over_scoreboard():
    payload = _no_block_payload(_oct26_roster(1), current=1)
    payload["proGamesByScoringPeriod"] = {"1": _games(2, 4, 5, 16, 14, 6, 30, 27)}

    class ExplodingScoreboard:
        def teams_on(self, day):
            raise AssertionError("scoreboard must not be consulted")

        def first_regular_season_date(self, start, end):
            raise AssertionError("scoreboard must not be consulted")

    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client, scoreboard=ExplodingScoreboard())
    assert run["status"] == "ok"
    assert run["plan"]["schedule"]["source"] == "pro_games_block"


def test_no_date_run_uses_scoreboard_for_today():
    today = datetime.now(_ET).date()
    entries = [
        _entry(301, BE, _fb_player(301, 1, [PG, G, UTIL, BE], 30, proj_periods=(5,))),
        _entry(302, BE, _fb_player(302, 2, [SG, G, UTIL, BE], 28, proj_periods=(5,))),
        _entry(303, BE, _fb_player(303, 3, [SF, F, UTIL, BE], 27, proj_periods=(5,))),
        _entry(304, BE, _fb_player(304, 4, [PF, F, UTIL, BE], 26, proj_periods=(5,))),
        _entry(305, BE, _fb_player(305, 9, [C, UTIL, BE])),
    ]
    payload = _no_block_payload(entries, current=5)
    db = FakeSupabase()
    client = StatefulClient(payload)
    sb = FakeScoreboard({today: {1, 2, 3, 4}}, season_start=None)
    run = lineup.run_lineup(db, dict(ACCOUNT), client, scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 5
    assert run["plan"]["schedule"]["source"] == "scoreboard"
    assert run["plan"]["schedule"]["target_date"] == today.isoformat()
    # the scoreboard was asked about today's ET date, nothing else
    assert sb.calls == [("teams_on", today)]


def test_no_date_preseason_keeps_clean_error():
    # Season has not started yet: the first regular-season date is a
    # week in the future, so a no-date run keeps the legacy clean
    # (silent) error instead of resolving a period.
    today = datetime.now(_ET).date()
    payload = _no_block_payload(_oct26_roster(6), current=None)
    db = FakeSupabase()
    client = StatefulClient(payload)
    sb = FakeScoreboard({}, season_start=today + timedelta(days=7))
    run = lineup.run_lineup(db, dict(ACCOUNT), client, scoreboard=sb)
    assert run["status"] == "error"
    assert "currentScoringPeriod" in run["error"]
    assert client.posts == []
    # the scoreboard was consulted only to learn the season start
    assert sb.calls == [
        ("first_regular_season_date", date(2026, 10, 1), date(2026, 11, 30))
    ]


def test_no_date_run_without_current_resolves_today_via_scoreboard():
    # Opening-day shape (2026-10-20): the league payload carries NO
    # currentScoringPeriod even though the season HAS started. The
    # no-date run must resolve today via the scoreboard fallback
    # (period 1 = the first regular-season date) instead of erroring.
    today = datetime.now(_ET).date()
    payload = _no_block_payload(_oct26_roster(1), current=None)
    db = FakeSupabase()
    client = StatefulClient(payload)
    sb = FakeScoreboard({today: OCT26_SLATE}, season_start=today)
    run = lineup.run_lineup(db, dict(ACCOUNT), client, scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 1
    schedule = run["plan"]["schedule"]
    assert schedule["source"] == "scoreboard"
    assert schedule["target_date"] == today.isoformat()
    assert schedule["season_start_date"] == today.isoformat()
    assert schedule["anchor_period"] == 1
    plan = {p["player_id"]: p for p in run["plan"]["players"]}
    for pid in range(101, 111):
        assert plan[pid]["scheduled"] is True
        assert plan[pid]["to_slot"] in STARTING
    (post,) = client.posts
    assert post["scoring_period_id"] == 1


def test_explicit_period_with_no_current_uses_season_anchor():
    # No currentScoringPeriod (preseason payload), an explicit future
    # period: its date comes from the season-start anchor.
    payload = _no_block_payload(_oct26_roster(6), current=None)
    db = FakeSupabase()
    client = StatefulClient(payload)
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, scoring_period_id=6, scoreboard=sb
    )
    assert run["status"] == "ok"
    assert run["plan"]["schedule"]["source"] == "scoreboard"
    assert run["plan"]["schedule"]["target_date"] == "2026-10-26"
    (post,) = client.posts
    assert post["scoring_period_id"] == 6


def test_fallback_gate_failure_on_explicit_period_aborts():
    # Period 6's projections cover teams that are NOT playing on the
    # derived date: the gate refuses and nothing is submitted.
    entries = [
        _entry(401, BE, _fb_player(401, 21, [PG, G, UTIL, BE], 25, proj_periods=(6,))),
        _entry(402, BE, _fb_player(402, 22, [SG, UTIL, BE], 24, proj_periods=(6,))),
        _entry(403, BE, _fb_player(403, 1, [UTIL, BE])),
    ]
    payload = _no_block_payload(entries, current=None)
    db = FakeSupabase()
    client = StatefulClient(payload)
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, scoring_period_id=6, scoreboard=sb
    )
    assert run["status"] == "error"
    assert "schedule gate" in run["error"]
    assert client.posts == []


def test_schedule_gate_rule():
    passed, detail = lineup._schedule_gate({1, 2, 3}, {1, 2, 3})
    assert passed and detail["verdict"] == "match"
    passed, _ = lineup._schedule_gate(set(), set())
    assert passed  # consistent no-games day
    passed, _ = lineup._schedule_gate({1, 2}, set())
    assert not passed
    passed, _ = lineup._schedule_gate(set(), {1, 2})
    assert not passed
    # a neighbouring slate shares only half the teams: both
    # coverages collapse below the threshold
    passed, detail = lineup._schedule_gate({1, 2, 3, 4}, {1, 2, 5, 6})
    assert not passed and detail["verdict"] == "poor overlap"
    # one unrostered playing team out of ten still passes
    passed, _ = lineup._schedule_gate(set(range(1, 11)), set(range(1, 10)))
    assert passed


# --- runner: kona-sourced gate projections (round 2) -----------------------------
#
# The live preseason failure this section pins: ESPN publishes NO
# per-day projected splits inside roster payloads, so the gate's P
# was empty for EVERY candidate period and the consistency gate
# rejected all of them. Per-day projections live in the kona player
# feed (filtered by scoring period); when neither source has any,
# the run resolves by the deterministic formula alone and records
# the unverifiable marker.


class KonaClient(StatefulClient):
    """StatefulClient + a kona period feed.

    ``kona`` maps scoring_period_id -> entries (or an Exception
    instance to raise). Every period asked for is recorded.
    """

    def __init__(self, payload, kona=None):
        super().__init__(payload)
        self.kona = kona or {}
        self.kona_calls = []

    def get_players_for_period(self, scoring_period_id, limit=1000):
        self.kona_calls.append(scoring_period_id)
        result = self.kona.get(scoring_period_id, [])
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


def _kona_entry(pid, team, periods):
    """One kona player-feed entry: the player sits at the top level
    (unlike roster entries' playerPoolEntry nesting)."""
    player = _fb_player(pid, team, [PG, G, UTIL, BE], 20, proj_periods=periods)
    return {"id": pid, "onTeamId": None, "player": player}


def _kona_slate(period, teams=OCT26_SLATE):
    """Kona entries projecting exactly ``teams`` for ``period``."""
    return [
        _kona_entry(900 + i, team, (period,))
        for i, team in enumerate(sorted(teams))
    ]


def _strip_projections(entries):
    """The preseason roster shape: same players, NO projected splits
    anywhere in the payload."""
    out = copy.deepcopy(entries)
    for e in out:
        e["playerPoolEntry"]["player"]["stats"] = []
    return out


def _gate_candidates(run):
    return json.loads(run["error"].split("gate candidates: ", 1)[1])["candidates"]


def test_date_run_gate_passes_via_kona_when_roster_publishes_no_projections():
    db = FakeSupabase()
    payload = _no_block_payload(_strip_projections(_oct26_roster(6)))
    client = KonaClient(payload, kona={6: _kona_slate(6)})
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 6
    schedule = run["plan"]["schedule"]
    assert schedule["candidate_offset"] == 0
    assert schedule["gate"]["verdict"] == "match"
    assert schedule["gate"]["p_source"] == "kona"
    (attempt,) = schedule["candidates_tried"]
    assert attempt["p_source"] == "kona"
    assert attempt["projected_count"] == len(OCT26_SLATE)
    assert attempt["overlap"] == len(OCT26_SLATE)
    # the anchor passed at once: exactly one kona fetch, no more
    assert client.kona_calls == [6]
    (post,) = client.posts
    assert post["scoring_period_id"] == 6


def test_date_run_gate_rejection_via_kona_carries_candidate_diagnostics():
    # Kona HAS projections — for teams that are not playing that
    # day. A genuine mismatch: the gate must still refuse, and the
    # recorded error run carries the per-candidate numbers.
    disjoint = {21, 22, 23}
    kona = {p: _kona_slate(p, disjoint) for p in range(1, 15)}
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona=kona
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "error"
    assert "schedule gate" in run["error"]
    assert run["plan"] is None
    assert client.posts == []
    candidates = _gate_candidates(run)
    assert [c["period"] for c in candidates] == [6, 5, 7, 4, 8, 3, 9]
    for c in candidates:
        assert c["passed"] is False
        assert c["scoreboard_count"] == len(OCT26_SLATE)
        assert c["projected_count"] == len(disjoint)
        assert c["overlap"] == 0
        assert c["p_source"] == "kona"


def test_date_run_formula_only_when_no_projections_exist_anywhere():
    # Roster publishes nothing AND kona answers empty for every
    # period: the gate has nothing to check, so the run proceeds on
    # the deterministic formula (the anchor period), records the
    # unverifiable marker, and still plans from the scoreboard slate.
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona={}
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 6  # the formula's anchor
    schedule = run["plan"]["schedule"]
    assert schedule["gate"] == "unverifiable_no_projection_data"
    assert schedule["anchor_period"] == 6
    assert schedule["candidate_offset"] == 0
    assert schedule["formula"]["first_scoring_period"] == 1
    assert schedule["formula"]["days_since_season_start"] == 5
    # every candidate was checked in BOTH sources before falling back
    assert sorted(set(client.kona_calls)) == [3, 4, 5, 6, 7, 8, 9]
    # scheduled still comes from the authoritative scoreboard slate
    plan = {p["player_id"]: p for p in run["plan"]["players"]}
    assert all(plan[pid]["scheduled"] for pid in range(101, 111))
    (post,) = client.posts
    assert post["scoring_period_id"] == 6


def test_date_run_dry_run_formula_only_submits_nothing():
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona={}
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, date="2026-10-26", dry_run=True, scoreboard=sb
    )
    assert run["status"] == "dry_run"
    assert run["scoring_period_id"] == 6
    assert run["plan"]["schedule"]["gate"] == "unverifiable_no_projection_data"
    assert client.posts == []


def test_formula_fallback_unreachable_when_any_candidate_has_projections():
    # Period 5 DOES have projections (for the wrong teams): data
    # exists, so the full gate applies, nothing passes, and the
    # formula-only fallback must not fire.
    kona = {5: _kona_slate(5, {21, 22, 23})}
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona=kona
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "error"
    assert "schedule gate" in run["error"]
    assert client.posts == []


def test_kona_error_blocks_formula_fallback_and_is_diagnosed():
    # A kona outage is not "no projections published": the check
    # never completed, so the fallback must not fire — and the
    # recorded diagnostics say why.
    kona = {p: EspnError("kona down", status=500) for p in range(1, 15)}
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona=kona
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "error"
    assert client.posts == []
    candidates = _gate_candidates(run)
    assert candidates
    assert all(c["p_source"] == "none" for c in candidates)
    assert all(c["p_note"].startswith("kona_error") for c in candidates)


def test_kona_auth_failure_records_auth_error_run():
    kona = {6: EspnAuthError("ESPN players -> 401: re-onboard", status=401)}
    db = FakeSupabase()
    client = KonaClient(
        _no_block_payload(_strip_projections(_oct26_roster(6))), kona=kona
    )
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26", scoreboard=sb)
    assert run["status"] == "auth_error"
    assert run["conflicts"][0]["kind"] == "auth"
    assert client.posts == []


def test_explicit_period_gate_passes_via_kona():
    payload = _no_block_payload(_strip_projections(_oct26_roster(6)), current=None)
    db = FakeSupabase()
    client = KonaClient(payload, kona={6: _kona_slate(6)})
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, scoring_period_id=6, scoreboard=sb
    )
    assert run["status"] == "ok"
    schedule = run["plan"]["schedule"]
    assert schedule["gate"]["verdict"] == "match"
    assert schedule["gate"]["p_source"] == "kona"
    assert schedule["target_date"] == "2026-10-26"
    (post,) = client.posts
    assert post["scoring_period_id"] == 6


def test_explicit_period_formula_only_when_no_projections():
    payload = _no_block_payload(_strip_projections(_oct26_roster(6)), current=None)
    db = FakeSupabase()
    client = KonaClient(payload, kona={})
    sb = FakeScoreboard({OCT26: OCT26_SLATE})
    run = lineup.run_lineup(
        db, dict(ACCOUNT), client, scoring_period_id=6, scoreboard=sb
    )
    assert run["status"] == "ok"
    assert run["plan"]["schedule"]["gate"] == "unverifiable_no_projection_data"
    (post,) = client.posts
    assert post["scoring_period_id"] == 6
