"""Unit tests for ESPN Fantasy v2: automatic daily lineup setting.

Everything is mocked — the ESPN wire (stateful fake client / stubbed
urlopen), Supabase (in-memory table fake), and account resolution. No live
ESPN calls: no account needs to be onboarded for these tests.

Covers: full-coverage day (no conflict), slot-overflow conflict,
eligibility-jam conflict, OUT player benched without conflict (and
QUESTIONABLE counting as scheduled), IR activation, a scheduled player
stuck on IR, auth failure recorded as an auth_error run, verify
mismatch, idempotent re-run, dry-run submitting nothing, date ->
scoring-period resolution (incl. the adhoc future-day path), tenant
isolation of the run log, the write client's payload/auth mapping, the
HTTP routes, and the MCP tools.
"""

import asyncio
import copy
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import espn_client, lineup, routes
from espn.accounts import AccountError
from espn.espn_client import EspnAuthError, EspnClient, EspnError

PG, SG, SF, PF, C, G, F, UTIL, BE, IR = 0, 1, 2, 3, 4, 5, 6, 11, 12, 13
STARTING = {PG, SG, SF, PF, C, G, F, UTIL}
PERIOD = 5
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


# --- fixture builders ----------------------------------------------------------


def _player(pid, team, eligible, value=None, status="ACTIVE", period=PERIOD):
    stats = []
    if value is not None:
        stats.append(
            {
                "statSourceId": 1,  # ESPN projection for the target day
                "statSplitTypeId": 5,
                "scoringPeriodId": period,
                "appliedTotal": float(value),
            }
        )
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
    return {
        "playerId": pid,
        "lineupSlotId": slot,
        "playerPoolEntry": {"player": player},
    }


def _games(*team_ids, date_ms=None):
    games = []
    ids = list(team_ids)
    for i in range(0, len(ids), 2):
        game = {"homeProTeamId": ids[i]}
        if i + 1 < len(ids):
            game["awayProTeamId"] = ids[i + 1]
        if date_ms is not None:
            game["date"] = date_ms
        games.append(game)
    return games


def _payload(entries, games_by_period, current=PERIOD):
    return {
        "id": 999,
        "seasonId": 2027,
        "status": {"currentScoringPeriod": current, "firstScoringPeriod": 1},
        "settings": {
            "rosterSettings": {
                "lineupSlotCounts": {
                    "0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                    "5": 1, "6": 1, "11": 3, "12": 3, "13": 1,
                }
            },
            "scoringSettings": {"scoringItems": [{"statId": 0, "points": 1.0}]},
        },
        "teams": [
            {"id": 7, "owners": [SWID], "roster": {"entries": entries}}
        ],
        "proGamesByScoringPeriod": {
            str(k): v for k, v in games_by_period.items()
        },
    }


def _full_coverage_payload(period=PERIOD):
    """10 scheduled players (teams 1-4 play) who all fit; bench/IR hold
    no-game players and one OUT player parked on IR."""
    entries = [
        _entry(11, PG, _player(11, 9, [PG, G, UTIL, BE], period=period)),
        _entry(10, SG, _player(10, 2, [SG, UTIL, BE], 18, period=period)),
        _entry(12, SF, _player(12, 9, [SF, F, UTIL, BE], period=period)),
        _entry(13, PF, _player(13, 9, [PF, F, UTIL, BE], period=period)),
        _entry(9, C, _player(9, 4, [C, UTIL, BE], 19, period=period)),
        _entry(6, G, _player(6, 2, [PG, SG, G, UTIL, BE], 24, period=period)),
        _entry(7, F, _player(7, 3, [SF, PF, F, UTIL, BE], 23, period=period)),
        _entry(4, UTIL, _player(4, 2, [PF, F, UTIL, BE], 26, period=period)),
        _entry(1, UTIL, _player(1, 1, [PG, G, UTIL, BE], 30, period=period)),
        _entry(2, UTIL, _player(2, 1, [SG, G, UTIL, BE], 28, period=period)),
        _entry(3, BE, _player(3, 1, [SF, F, UTIL, BE], 27, period=period)),
        _entry(5, BE, _player(5, 3, [C, UTIL, BE], 35, period=period)),
        _entry(8, BE, _player(8, 1, [UTIL, BE], 20, period=period)),
        _entry(14, IR, _player(14, 1, [C, UTIL, BE, IR], None,
                               status="OUT", period=period)),
    ]
    return _payload(entries, {period: _games(1, 2, 3, 4)}, current=period)


# --- fakes ---------------------------------------------------------------------


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None

    def _base(self):
        return self._rows if self._rows is not None else list(self._store)

    def insert(self, row):
        row = dict(row)
        row["id"] = f"run-{len(self._store) + 1}"
        row["created_at"] = (
            f"2026-10-15T00:00:{len(self._store):02d}+00:00"
        )
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
        self._rows = sorted(self._base(), key=lambda r: r.get(column),
                            reverse=desc)
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
    """ESPN fake whose roster mutates when a transaction is posted."""

    def __init__(self, payload, apply_posts=True):
        self.payload = payload
        self.apply_posts = apply_posts
        self.posts = []

    def get_league(self, views, scoring_period_id=None):
        return copy.deepcopy(self.payload)

    def post_lineup_transaction(self, member_id, team_id,
                                scoring_period_id, items):
        self.posts.append(
            {
                "member_id": member_id,
                "team_id": team_id,
                "scoring_period_id": scoring_period_id,
                "items": items,
            }
        )
        if self.apply_posts:
            entries = self.payload["teams"][0]["roster"]["entries"]
            by_id = {e["playerId"]: e for e in entries}
            for item in items:
                by_id[item["playerId"]]["lineupSlotId"] = item[
                    "toLineupSlotId"
                ]
        return {"status": "EXECUTED"}


class AuthFailClient:
    def get_league(self, views, scoring_period_id=None):
        raise EspnAuthError(
            "ESPN rejected the stored cookies (HTTP 401); "
            "re-onboard with fresh espn_s2/SWID cookies"
        )

    def post_lineup_transaction(self, **kw):
        raise AssertionError("must not post after an auth failure")


def _plan_players(run):
    return {p["player_id"]: p for p in run["plan"]["players"]}


# --- planner + runner: the happy path ------------------------------------------


def test_full_coverage_day_no_conflict():
    db = FakeSupabase()
    client = StatefulClient(_full_coverage_payload())
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    assert run["scoring_period_id"] == PERIOD
    plan = _plan_players(run)
    assert set(run["plan"]["scheduled_player_ids"]) == set(range(1, 11))
    for pid in range(1, 11):
        assert plan[pid]["to_slot"] in STARTING
    # the OUT player stays parked on IR and is not "scheduled"
    assert plan[14]["to_slot"] == IR
    assert plan[14]["scheduled"] is False
    # exactly one transaction, for this team/period, LINEUP moves only
    (post,) = client.posts
    assert post["team_id"] == 7
    assert post["scoring_period_id"] == PERIOD
    assert post["items"] == run["moves"]
    # the run was persisted
    assert len(db._store) == 1
    assert db._store[0]["status"] == "ok"
    assert db._store[0]["account_id"] == "acc-1"


def test_idempotent_rerun_submits_nothing():
    db = FakeSupabase()
    client = StatefulClient(_full_coverage_payload())
    first = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert first["status"] == "ok"
    assert len(client.posts) == 1
    second = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert second["status"] == "noop"
    assert second["moves"] == []
    assert second["conflicts"] == []
    assert len(client.posts) == 1  # no second transaction
    assert len(db._store) == 2


def test_dry_run_records_plan_and_submits_nothing():
    db = FakeSupabase()
    client = StatefulClient(_full_coverage_payload())
    run = lineup.run_lineup(db, dict(ACCOUNT), client, dry_run=True)
    assert run["status"] == "dry_run"
    assert run["mode"] == "dry_run"
    assert run["plan"]["moves"]  # a real plan was computed
    assert client.posts == []
    assert db._store[0]["mode"] == "dry_run"


def test_verify_mismatch_is_recorded():
    db = FakeSupabase()
    # ESPN "accepts" the transaction but the roster never changes.
    client = StatefulClient(_full_coverage_payload(), apply_posts=False)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "verify_mismatch"
    assert run["conflicts"]
    assert {c["kind"] for c in run["conflicts"]} == {"verify_mismatch"}
    assert len(client.posts) == 1


# --- conflicts -------------------------------------------------------------------


def test_slot_overflow_conflict_lowest_value_sits():
    entries = [
        _entry(1, BE, _player(1, 1, [PG, G, UTIL, BE], 30)),
        _entry(2, BE, _player(2, 1, [SG, G, UTIL, BE], 28)),
        _entry(3, BE, _player(3, 2, [SF, F, UTIL, BE], 27)),
        _entry(4, UTIL, _player(4, 2, [PF, F, UTIL, BE], 26)),
        _entry(5, C, _player(5, 3, [C, UTIL, BE], 35)),
        _entry(6, PG, _player(6, 2, [PG, SG, G, UTIL, BE], 24)),
        _entry(7, F, _player(7, 3, [SF, PF, F, UTIL, BE], 23)),
        _entry(8, UTIL, _player(8, 4, [UTIL, BE], 20)),
        _entry(9, UTIL, _player(9, 4, [C, UTIL, BE], 19)),
        _entry(10, SG, _player(10, 2, [SG, UTIL, BE], 18)),
        # 11th scheduled player — the lowest projection sits
        _entry(13, PF, _player(13, 3, [PF, F, UTIL, BE], 6)),
        _entry(11, G, _player(11, 9, [PG, G, UTIL, BE])),
        _entry(12, SF, _player(12, 9, [SF, F, UTIL, BE])),
        _entry(14, IR, _player(14, 1, [C, UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["kind"] == "slot_overflow"
    assert conflict["player_id"] == 13
    assert conflict["player_name"] == "Player 13"
    assert conflict["scoring_period_id"] == PERIOD
    assert conflict["detail"]["scheduled_count"] == 11
    assert conflict["detail"]["starting_slots"] == 10
    assert conflict["detail"]["value"] == 6
    # the comparison behind the choice is recorded: the weakest
    # scheduled player who kept a starting slot projected 18
    assert conflict["detail"]["value_source"] == "day_projection"
    assert conflict["detail"]["lowest_starter_value"] == 18
    assert conflict["detail"]["lowest_starter_player_id"] == 10
    assert conflict["detail"]["lowest_starter_value_source"] == (
        "day_projection"
    )
    # the best legal lineup is still submitted; the sitter goes to BE
    assert len(client.posts) == 1
    assert run["plan"]["sitting_player_ids"] == [13]
    assert _plan_players(run)[13]["to_slot"] == BE


def _recent7_player(pid, team, eligible, ppg, status="ACTIVE"):
    """A player with no day projection: value comes from last-7-days
    form (statSplitTypeId 2, a 7-day total)."""
    player = _player(pid, team, eligible, None, status=status)
    player["stats"] = [
        {
            "statSourceId": 0,
            "statSplitTypeId": 2,
            "appliedTotal": float(ppg) * 7.0,
        }
    ]
    return player


def test_slot_overflow_sitter_ranked_by_recent7_ppg_without_projection():
    # Warner's ranking preference (2026-10-23): with no real day
    # projection published, the sitter is chosen by recent/season
    # fantasy PPG — here recent-7 form.
    entries = [
        _entry(1, BE, _recent7_player(1, 1, [PG, G, UTIL, BE], 30)),
        _entry(2, BE, _recent7_player(2, 1, [SG, G, UTIL, BE], 28)),
        _entry(3, BE, _recent7_player(3, 2, [SF, F, UTIL, BE], 27)),
        _entry(4, UTIL, _recent7_player(4, 2, [PF, F, UTIL, BE], 26)),
        _entry(5, C, _recent7_player(5, 3, [C, UTIL, BE], 35)),
        _entry(6, PG, _recent7_player(6, 2, [PG, SG, G, UTIL, BE], 24)),
        _entry(7, F, _recent7_player(7, 3, [SF, PF, F, UTIL, BE], 23)),
        _entry(8, UTIL, _recent7_player(8, 4, [UTIL, BE], 20)),
        _entry(9, UTIL, _recent7_player(9, 4, [C, UTIL, BE], 19)),
        _entry(10, SG, _recent7_player(10, 2, [SG, UTIL, BE], 18)),
        # 11th scheduled player — the lowest recent-7 PPG sits
        _entry(13, PF, _recent7_player(13, 3, [PF, F, UTIL, BE], 6)),
        _entry(11, G, _player(11, 9, [PG, G, UTIL, BE])),
        _entry(12, SF, _player(12, 9, [SF, F, UTIL, BE])),
        _entry(14, IR, _player(14, 1, [C, UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["kind"] == "slot_overflow"
    assert conflict["player_id"] == 13
    assert conflict["detail"]["value"] == 6
    assert conflict["detail"]["value_source"] == "recent7"
    assert conflict["detail"]["lowest_starter_value"] == 18
    assert conflict["detail"]["lowest_starter_value_source"] == "recent7"
    assert run["plan"]["sitting_player_ids"] == [13]
    assert _plan_players(run)[13]["to_slot"] == BE


def test_eligibility_jam_conflict():
    entries = [
        _entry(21, BE, _player(21, 1, [C, BE], 30)),   # C-only
        _entry(22, C, _player(22, 2, [C, BE], 25)),    # C-only: jams
        _entry(23, PG, _player(23, 1, [PG, G, UTIL, BE], 28)),
        _entry(24, SG, _player(24, 2, [SG, G, UTIL, BE], 27)),
        _entry(25, SF, _player(25, 3, [SF, F, UTIL, BE], 26)),
        _entry(26, PF, _player(26, 3, [PF, F, UTIL, BE], 24)),
        _entry(27, G, _player(27, 4, [PG, SG, G, UTIL, BE], 23)),
        _entry(28, F, _player(28, 4, [SF, PF, F, UTIL, BE], 22)),
        _entry(29, UTIL, _player(29, 1, [UTIL, BE], 21)),
        _entry(30, UTIL, _player(30, 2, [UTIL, BE], 20)),
        _entry(31, UTIL, _player(31, 9, [UTIL, BE])),
        _entry(32, BE, _player(32, 9, [PG, UTIL, BE])),
        _entry(33, IR, _player(33, 9, [UTIL, BE, IR])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["kind"] == "eligibility_jam"
    assert conflict["player_id"] == 22
    # the lower-value C-only player (25) lost the contested C slot to
    # the higher-value one (30); the detail records that he actually
    # out-valued the weakest starter kept elsewhere (20) — he sat on
    # eligibility, not value
    assert conflict["detail"]["value"] == 25
    assert conflict["detail"]["lowest_starter_value"] == 20
    assert conflict["detail"]["lowest_starter_player_id"] == 30
    plan = _plan_players(run)
    assert plan[21]["to_slot"] == C
    assert plan[22]["to_slot"] == BE
    assert len(client.posts) == 1


def test_eligibility_jam_higher_value_wins_the_contested_slot():
    # Same jam shape, values swapped: the C-only player on the bench
    # (30) takes C from the lower-value incumbent (25), who sits.
    entries = [
        _entry(21, BE, _player(21, 1, [C, BE], 25)),   # C-only
        _entry(22, C, _player(22, 2, [C, BE], 30)),    # C-only: wins
        _entry(23, PG, _player(23, 1, [PG, G, UTIL, BE], 28)),
        _entry(24, SG, _player(24, 2, [SG, G, UTIL, BE], 27)),
        _entry(25, SF, _player(25, 3, [SF, F, UTIL, BE], 26)),
        _entry(26, PF, _player(26, 3, [PF, F, UTIL, BE], 24)),
        _entry(27, G, _player(27, 4, [PG, SG, G, UTIL, BE], 23)),
        _entry(28, F, _player(28, 4, [SF, PF, F, UTIL, BE], 22)),
        _entry(29, UTIL, _player(29, 1, [UTIL, BE], 21)),
        _entry(30, UTIL, _player(30, 2, [UTIL, BE], 20)),
        _entry(31, UTIL, _player(31, 9, [UTIL, BE])),
        _entry(32, BE, _player(32, 9, [PG, UTIL, BE])),
        _entry(33, IR, _player(33, 9, [UTIL, BE, IR])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["kind"] == "eligibility_jam"
    assert conflict["player_id"] == 21
    assert conflict["detail"]["value"] == 25
    plan = _plan_players(run)
    assert plan[22]["to_slot"] == C
    assert plan[21]["to_slot"] == BE
    assert run["plan"]["sitting_player_ids"] == [21]


def test_out_player_benched_no_conflict_and_gtd_counts():
    entries = [
        _entry(41, BE, _player(41, 1, [PG, G, UTIL, BE], 30)),
        _entry(42, BE, _player(42, 2, [SG, G, UTIL, BE], 28)),
        _entry(43, BE, _player(43, 1, [SF, F, UTIL, BE], 27)),
        _entry(44, SF, _player(44, 3, [PF, F, UTIL, BE], 26)),
        _entry(45, C, _player(45, 4, [C, UTIL, BE], 35)),
        _entry(46, G, _player(46, 2, [PG, SG, G, UTIL, BE], 24)),
        _entry(47, F, _player(47, 3, [SF, PF, F, UTIL, BE], 23)),
        # QUESTIONABLE still counts as scheduled
        _entry(48, UTIL, _player(48, 1, [UTIL, BE], 20,
                                 status="QUESTIONABLE")),
        _entry(49, UTIL, _player(49, 4, [C, UTIL, BE], 19)),
        _entry(50, SG, _player(50, 2, [SG, UTIL, BE], 18)),
        # OUT with a huge projection: benches anyway, never a conflict
        _entry(51, UTIL, _player(51, 1, [UTIL, BE, IR], 99, status="OUT")),
        _entry(52, PG, _player(52, 9, [PG, UTIL, BE])),
        _entry(53, PF, _player(53, 9, [PF, UTIL, BE])),
        _entry(54, IR, _player(54, 9, [UTIL, BE, IR])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    run = lineup.run_lineup(db, dict(ACCOUNT), StatefulClient(payload))
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    plan = _plan_players(run)
    assert plan[48]["scheduled"] is True
    assert plan[48]["to_slot"] in STARTING
    assert plan[51]["scheduled"] is False
    assert plan[51]["out"] is True
    assert plan[51]["to_slot"] == BE


def test_healthy_displaced_starter_goes_to_bench_never_ir():
    # Opening-day 2026-10-20 regression: only Cason Wallace (here
    # pid 2) is scheduled; he takes the PG slot from a healthy
    # Harden-like starter (pid 1, lowest id, so he is placed first
    # among the unscheduled starters). The bench is full and the IR
    # slot is empty — the old planner parked him on IR and ESPN
    # rejected the whole transaction ("player is not injured").
    entries = [
        _entry(1, PG, _player(1, 9, [PG, G, UTIL, BE, IR])),
        _entry(2, G, _player(2, 1, [PG, G, UTIL, BE], 25)),
        _entry(3, SG, _player(3, 9, [SG, G, UTIL, BE])),
        _entry(4, SF, _player(4, 9, [SF, F, UTIL, BE])),
        _entry(5, PF, _player(5, 9, [PF, F, UTIL, BE])),
        _entry(6, C, _player(6, 9, [C, UTIL, BE])),
        _entry(7, F, _player(7, 9, [SF, PF, F, UTIL, BE])),
        _entry(8, UTIL, _player(8, 9, [UTIL, BE])),
        _entry(9, UTIL, _player(9, 9, [UTIL, BE])),
        _entry(10, UTIL, _player(10, 9, [UTIL, BE])),
        _entry(11, BE, _player(11, 9, [UTIL, BE])),
        _entry(12, BE, _player(12, 9, [UTIL, BE])),
        _entry(13, BE, _player(13, 9, [UTIL, BE])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    plan = _plan_players(run)
    assert plan[2]["scheduled"] is True
    assert plan[2]["to_slot"] == PG
    assert plan[1]["out"] is False
    assert plan[1]["to_slot"] == BE
    # nobody is planned into IR, and no submitted move targets IR
    assert all(p["to_slot"] != IR for p in plan.values())
    assert all(m["toLineupSlotId"] != IR for m in run["moves"])
    moves = {m["playerId"]: m for m in run["moves"]}
    assert moves[1]["toLineupSlotId"] == BE
    assert moves[2]["toLineupSlotId"] == PG
    # the displaced starter is UNSCHEDULED and the only scheduled
    # player starts: no conflict, non-conflict status — the old
    # planner emitted a spurious "no legal bench/IR slot"
    # eligibility_jam for exactly this shape (Warner, 2026-10-23)
    assert run["conflicts"] == []
    assert run["status"] == "ok"
    assert run["plan"]["sitting_player_ids"] == []


def test_unscheduled_starter_swapped_to_bench_is_not_a_conflict():
    # 2026-10-23 live shape: a scheduled bench player (Boozer-like,
    # pid 2) swaps into SF with an unscheduled starter (Mobley-like,
    # pid 1) while the bench is full of other unscheduled players.
    # Every scheduled player starts and the swap applies cleanly on
    # ESPN (Mobley went 3 -> 12 live), so: zero conflicts, ok status.
    entries = [
        _entry(1, SF, _player(1, 9, [SF, F, UTIL, BE])),
        _entry(2, BE, _player(2, 1, [SF, F, UTIL, BE], 20)),
        _entry(3, PG, _player(3, 9, [PG, G, UTIL, BE])),
        _entry(4, SG, _player(4, 9, [SG, G, UTIL, BE])),
        _entry(5, PF, _player(5, 9, [PF, F, UTIL, BE])),
        _entry(6, C, _player(6, 9, [C, UTIL, BE])),
        _entry(7, G, _player(7, 9, [PG, SG, G, UTIL, BE])),
        _entry(8, F, _player(8, 9, [SF, PF, F, UTIL, BE])),
        _entry(9, UTIL, _player(9, 9, [UTIL, BE])),
        _entry(10, UTIL, _player(10, 9, [UTIL, BE])),
        _entry(11, UTIL, _player(11, 9, [UTIL, BE])),
        _entry(12, BE, _player(12, 9, [UTIL, BE])),
        _entry(13, BE, _player(13, 9, [UTIL, BE])),
        _entry(14, BE, _player(14, 9, [UTIL, BE])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    assert run["plan"]["sitting_player_ids"] == []
    plan = _plan_players(run)
    assert plan[2]["scheduled"] is True
    assert plan[2]["to_slot"] == SF
    assert plan[1]["scheduled"] is False
    assert plan[1]["to_slot"] == BE
    moves = {m["playerId"]: m for m in run["moves"]}
    assert moves[2]["toLineupSlotId"] == SF
    assert moves[1]["toLineupSlotId"] == BE


def test_ir_activation_and_out_player_parked():
    entries = [
        _entry(61, PG, _player(61, 1, [PG, G, UTIL, BE], 30)),
        _entry(62, SG, _player(62, 2, [SG, G, UTIL, BE], 28)),
        _entry(63, SF, _player(63, 1, [SF, F, UTIL, BE], 27)),
        _entry(64, PF, _player(64, 3, [PF, F, UTIL, BE], 26)),
        # healthy + scheduled, stuck on IR: activated into the C slot
        _entry(65, IR, _player(65, 1, [C, UTIL, BE, IR], 33)),
        _entry(66, G, _player(66, 2, [PG, SG, G, UTIL, BE], 24)),
        _entry(67, F, _player(67, 3, [SF, PF, F, UTIL, BE], 23)),
        _entry(68, UTIL, _player(68, 4, [UTIL, BE], 20)),
        _entry(69, UTIL, _player(69, 4, [UTIL, BE], 19)),
        _entry(70, BE, _player(70, 2, [UTIL, BE], 18)),
        _entry(71, C, _player(71, 9, [C, UTIL, BE])),
        _entry(72, BE, _player(72, 9, [UTIL, BE])),
        _entry(73, UTIL, _player(73, 9, [UTIL, BE])),
        # OUT player parks onto the freed IR slot
        _entry(74, BE, _player(74, 2, [UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    plan = _plan_players(run)
    assert plan[65]["to_slot"] == C
    assert plan[74]["to_slot"] == IR
    moves = {m["playerId"]: m for m in run["moves"]}
    assert moves[65]["fromLineupSlotId"] == IR
    assert moves[65]["toLineupSlotId"] == C
    assert moves[74]["toLineupSlotId"] == IR


def test_scheduled_player_stuck_on_ir_is_a_conflict():
    entries = [
        _entry(81, PG, _player(81, 1, [PG, G, UTIL, BE], 30)),
        _entry(82, SG, _player(82, 2, [SG, G, UTIL, BE], 29)),
        _entry(83, SF, _player(83, 1, [SF, F, UTIL, BE], 28)),
        _entry(84, PF, _player(84, 3, [PF, F, UTIL, BE], 27)),
        _entry(85, G, _player(85, 2, [PG, SG, G, UTIL, BE], 26)),
        _entry(86, F, _player(86, 3, [SF, PF, F, UTIL, BE], 25)),
        _entry(87, UTIL, _player(87, 4, [UTIL, BE], 24)),
        _entry(88, UTIL, _player(88, 4, [UTIL, BE], 23)),
        _entry(89, BE, _player(89, 2, [SG, UTIL, BE], 22)),
        _entry(90, C, _player(90, 1, [C, BE], 40)),       # C-only
        # healthy + scheduled but C-only and the C slot is taken: stuck
        _entry(91, IR, _player(91, 2, [C, BE, IR], 10)),
        _entry(92, BE, _player(92, 9, [UTIL, BE])),
        _entry(93, BE, _player(93, 9, [UTIL, BE])),
        _entry(94, UTIL, _player(94, 9, [UTIL, BE])),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    run = lineup.run_lineup(db, dict(ACCOUNT), StatefulClient(payload))
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["player_id"] == 91
    assert conflict["detail"]["on_ir"] is True
    plan = _plan_players(run)
    assert plan[91]["scheduled"] is True
    assert plan[91]["to_slot"] == IR  # left parked; ESPN never moved him


# --- permutation matrix (Warner, 2026-10-23) -------------------------------------
#
# Every test below pins one lineup-setting permutation with explicit
# expected plan / status / conflicts, per Warner's policy: all
# scheduled players start if legally possible; on overflow or a jam
# the higher fantasy-PPG player starts and the lower sits, with a
# conflict raised ONLY for a scheduled player who actually sits.

ALL_SLOTS = [PG, SG, SF, PF, C, G, F, UTIL, BE]


def test_matrix_all_scheduled_already_starting_noop():
    # Permutation 1: every scheduled player is already in the exact
    # slot the planner would give him -> no moves, noop, no conflicts.
    entries = [
        _entry(1, PG, _player(1, 1, [PG, BE], 30)),
        _entry(2, SG, _player(2, 1, [SG, BE], 29)),
        _entry(3, SF, _player(3, 2, [SF, BE], 28)),
        _entry(4, PF, _player(4, 2, [PF, BE], 27)),
        _entry(5, C, _player(5, 3, [C, BE], 26)),
        _entry(6, G, _player(6, 3, [G, BE], 25)),
        _entry(7, F, _player(7, 4, [F, BE], 24)),
        _entry(8, UTIL, _player(8, 4, [UTIL, BE], 23)),
        _entry(9, UTIL, _player(9, 1, [UTIL, BE], 22)),
        _entry(10, UTIL, _player(10, 2, [UTIL, BE], 21)),
        _entry(11, BE, _player(11, 9, [UTIL, BE])),
        _entry(12, BE, _player(12, 9, [UTIL, BE])),
        _entry(13, BE, _player(13, 9, [UTIL, BE])),
        _entry(14, IR, _player(14, 9, [UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "noop"
    assert run["moves"] == []
    assert run["conflicts"] == []
    assert client.posts == []
    plan = _plan_players(run)
    for p in plan.values():
        assert p["to_slot"] == p["from_slot"]


def test_matrix_scheduled_on_bench_swapped_in_no_conflict():
    # Permutation 2: scheduled players on the bench swap in over
    # unscheduled players occupying starting slots; the displaced
    # unscheduled players go to the bench. No conflicts.
    entries = [
        _entry(1, PG, _player(1, 1, [PG, G, UTIL, BE], 30)),
        _entry(2, SG, _player(2, 1, [SG, G, UTIL, BE], 29)),
        _entry(3, SF, _player(3, 2, [SF, F, UTIL, BE], 28)),
        _entry(4, PF, _player(4, 2, [PF, F, UTIL, BE], 27)),
        _entry(5, C, _player(5, 3, [C, UTIL, BE], 26)),
        _entry(6, G, _player(6, 3, [PG, SG, G, UTIL, BE], 25)),
        _entry(7, F, _player(7, 4, [SF, PF, F, UTIL, BE], 24)),
        # unscheduled players squatting in the UTIL slots
        _entry(8, UTIL, _player(8, 9, [UTIL, BE])),
        _entry(9, UTIL, _player(9, 9, [UTIL, BE])),
        _entry(10, UTIL, _player(10, 9, [UTIL, BE])),
        # scheduled players stuck on the bench
        _entry(11, BE, _player(11, 1, [UTIL, BE], 20)),
        _entry(12, BE, _player(12, 2, [UTIL, BE], 19)),
        _entry(13, BE, _player(13, 3, [UTIL, BE], 18)),
        _entry(14, IR, _player(14, 9, [UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    assert run["plan"]["sitting_player_ids"] == []
    plan = _plan_players(run)
    for pid in (11, 12, 13):
        assert plan[pid]["scheduled"] is True
        assert plan[pid]["to_slot"] == UTIL
    for pid in (8, 9, 10):
        assert plan[pid]["scheduled"] is False
        assert plan[pid]["to_slot"] == BE


def test_matrix_fewer_scheduled_than_slots_all_start():
    # Permutation 3: only 4 scheduled players for 10 slots. All four
    # start; unscheduled players keep the leftover starting slots
    # they can legally keep, the rest bench. No conflicts.
    entries = [
        _entry(1, BE, _player(1, 1, [PG, G, UTIL, BE], 30)),
        _entry(2, UTIL, _player(2, 2, [C, UTIL, BE], 28)),
        _entry(3, SG, _player(3, 3, [SG, G, UTIL, BE], 27)),
        _entry(4, BE, _player(4, 4, [SF, F, UTIL, BE], 26)),
        _entry(5, PG, _player(5, 9, [PG, G, UTIL, BE])),
        _entry(6, SF, _player(6, 9, [SF, F, UTIL, BE])),
        _entry(7, PF, _player(7, 9, [PF, F, UTIL, BE])),
        _entry(8, G, _player(8, 9, [PG, SG, G, UTIL, BE])),
        _entry(9, F, _player(9, 9, [SF, PF, F, UTIL, BE])),
        _entry(10, UTIL, _player(10, 9, [UTIL, BE])),
        _entry(11, C, _player(11, 9, [C, UTIL, BE])),
        _entry(12, BE, _player(12, 9, [UTIL, BE])),
        _entry(13, BE, _player(13, 9, [UTIL, BE])),
        _entry(14, IR, _player(14, 9, [UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    assert run["plan"]["sitting_player_ids"] == []
    plan = _plan_players(run)
    for pid in (1, 2, 3, 4):
        assert plan[pid]["scheduled"] is True
        assert plan[pid]["to_slot"] in STARTING
    # leftover slots keep their unscheduled occupants where legal
    for pid in (7, 8, 9, 10):
        assert plan[pid]["to_slot"] in STARTING


def test_matrix_full_slate_overflow_multiple_sitters_lowest_first():
    # Permutations 4 + 15: a full slate — 13 scheduled for 10 slots.
    # Exactly the three lowest-PPG scheduled players sit, conflicts
    # name them lowest-PPG first, and sitting_player_ids matches the
    # conflict order. Healthy sitters go to the bench, never IR (11).
    entries = []
    start_slots = [PG, SG, SF, PF, C, G, F, UTIL, UTIL, UTIL]
    for pid in range(1, 14):
        slot = start_slots[pid - 1] if pid <= 10 else BE
        entries.append(
            _entry(pid, slot, _player(pid, (pid % 4) + 1, ALL_SLOTS, 40 - pid))
        )
    entries.append(
        _entry(14, IR, _player(14, 1, [C, UTIL, BE, IR], None, status="OUT"))
    )
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    # values run 39 (pid 1) down to 27 (pid 13): lowest three sit,
    # reported lowest first
    assert run["plan"]["sitting_player_ids"] == [13, 12, 11]
    assert [c["player_id"] for c in run["conflicts"]] == [13, 12, 11]
    assert {c["kind"] for c in run["conflicts"]} == {"slot_overflow"}
    assert [c["detail"]["value"] for c in run["conflicts"]] == [27, 28, 29]
    for c in run["conflicts"]:
        assert c["detail"]["lowest_starter_value"] == 30
    plan = _plan_players(run)
    for pid in range(1, 11):
        assert plan[pid]["to_slot"] in STARTING
    for pid in (11, 12, 13):
        assert plan[pid]["to_slot"] == BE
    # no healthy player is ever planned to IR
    assert all(
        p["to_slot"] != IR for p in plan.values() if not p["out"]
    )
    assert plan[14]["to_slot"] == IR


def _dual_source_player(pid, team, day, recent_ppg):
    """Both a day projection AND recent-7 form, set up so the two
    sources disagree about who should sit."""
    player = _player(pid, team, ALL_SLOTS, None)
    player["stats"] = [
        {
            "statSourceId": 1,
            "statSplitTypeId": 5,
            "scoringPeriodId": PERIOD,
            "appliedTotal": float(day),
        },
        {
            "statSourceId": 0,
            "statSplitTypeId": 2,
            "appliedTotal": float(recent_ppg) * 7.0,
        },
    ]
    return player


def test_matrix_day_projection_beats_recent7_for_sitter():
    # Permutation 6: ranking precedence. Player 10 has the LOWEST day
    # projection (5) but elite recent form (50/game); player 11 has a
    # better projection (10) but terrible form (1/game). The real
    # projection decides: player 10 sits, player 11 starts.
    entries = [
        _entry(pid, BE, _dual_source_player(pid, (pid % 4) + 1, 19 + pid, 30))
        for pid in range(1, 10)
    ]
    entries.append(_entry(10, UTIL, _dual_source_player(10, 1, 5, 50)))
    entries.append(_entry(11, BE, _dual_source_player(11, 2, 10, 1)))
    entries.append(_entry(12, BE, _player(12, 9, [UTIL, BE])))
    entries.append(_entry(13, BE, _player(13, 9, [UTIL, BE])))
    entries.append(
        _entry(14, IR, _player(14, 9, [UTIL, BE, IR], None, status="OUT"))
    )
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["player_id"] == 10
    assert conflict["detail"]["value"] == 5
    assert conflict["detail"]["value_source"] == "day_projection"
    assert run["plan"]["sitting_player_ids"] == [10]
    assert _plan_players(run)[11]["to_slot"] in STARTING


def test_matrix_ppg_tie_breaks_by_lower_player_id():
    # Permutation 7: an exact PPG tie for the last starting slot is
    # deterministic — the planner processes (-value, player_id), so
    # the lower player id gets the slot and the higher id sits.
    entries = [
        _entry(pid, BE, _player(pid, (pid % 4) + 1, ALL_SLOTS, 31 - pid))
        for pid in range(1, 10)
    ]
    entries.append(_entry(10, UTIL, _player(10, 1, ALL_SLOTS, 10)))
    entries.append(_entry(11, BE, _player(11, 2, ALL_SLOTS, 10)))  # tied
    entries.append(_entry(12, BE, _player(12, 9, [UTIL, BE])))
    entries.append(_entry(13, BE, _player(13, 9, [UTIL, BE])))
    entries.append(
        _entry(14, IR, _player(14, 9, [UTIL, BE, IR], None, status="OUT"))
    )
    payload = _payload(entries, {PERIOD: _games(1, 2, 3, 4)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "conflict"
    (conflict,) = run["conflicts"]
    assert conflict["player_id"] == 11
    assert conflict["detail"]["value"] == 10
    assert run["plan"]["sitting_player_ids"] == [11]
    assert _plan_players(run)[10]["to_slot"] in STARTING


def test_matrix_zero_scheduled_players_no_conflict():
    # Permutation 12: nobody on the roster has a game (the slate is
    # two teams nobody rosters). No scheduled player can sit, so no
    # conflicts and no moves — the lineup is left exactly as-is.
    payload = _payload(
        _full_coverage_payload()["teams"][0]["roster"]["entries"],
        {PERIOD: _games(20, 21)},
    )
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "noop"
    assert run["moves"] == []
    assert run["conflicts"] == []
    assert run["plan"]["scheduled_player_ids"] == []
    assert run["plan"]["sitting_player_ids"] == []
    assert client.posts == []


def test_matrix_bench_full_and_ir_occupied_displaced_starter_benches():
    # Permutations 13 + 14: bench full AND IR occupied by an OUT
    # player. The one scheduled player swaps into SF; the displaced
    # unscheduled starter still lands on the bench (the old planner
    # emitted the spurious no_legal_slot conflict for this shape).
    entries = [
        _entry(1, SF, _player(1, 9, [SF, F, UTIL, BE])),
        _entry(2, BE, _player(2, 1, [SF, F, UTIL, BE], 20)),
        _entry(3, PG, _player(3, 9, [PG, G, UTIL, BE])),
        _entry(4, SG, _player(4, 9, [SG, G, UTIL, BE])),
        _entry(5, PF, _player(5, 9, [PF, F, UTIL, BE])),
        _entry(6, C, _player(6, 9, [C, UTIL, BE])),
        _entry(7, G, _player(7, 9, [PG, SG, G, UTIL, BE])),
        _entry(8, F, _player(8, 9, [SF, PF, F, UTIL, BE])),
        _entry(9, UTIL, _player(9, 9, [UTIL, BE])),
        _entry(10, UTIL, _player(10, 9, [UTIL, BE])),
        _entry(11, UTIL, _player(11, 9, [UTIL, BE])),
        _entry(12, BE, _player(12, 9, [UTIL, BE])),
        _entry(13, BE, _player(13, 9, [UTIL, BE])),
        _entry(14, BE, _player(14, 9, [UTIL, BE])),
        _entry(15, IR, _player(15, 9, [UTIL, BE, IR], None, status="OUT")),
    ]
    payload = _payload(entries, {PERIOD: _games(1, 2)})
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "ok"
    assert run["conflicts"] == []
    assert run["plan"]["sitting_player_ids"] == []
    plan = _plan_players(run)
    assert plan[2]["to_slot"] == SF
    assert plan[1]["to_slot"] == BE
    assert plan[15]["to_slot"] == IR
    # the healthy displaced starter did NOT go to the occupied IR
    assert all(
        p["to_slot"] != IR for p in plan.values() if not p["out"]
    )


def test_player_value_season_fallback():
    # Permutation 6 (cont.): with neither a day projection nor
    # recent-7 form, value falls back to season fantasy PPG (the
    # season total divided by the periods played so far).
    items = [{"stat_id": 0, "points": 1.0}]
    player = {
        "stats": [
            {"statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 100.0}
        ]
    }
    assert lineup.player_value(player, items, PERIOD) == (20.0, "season")


# --- failures ---------------------------------------------------------------------


def test_auth_failure_recorded_as_auth_error_run():
    db = FakeSupabase()
    run = lineup.run_lineup(db, dict(ACCOUNT), AuthFailClient())
    assert run["status"] == "auth_error"
    assert run["error"]
    (conflict,) = run["conflicts"]
    assert conflict["kind"] == "auth"
    assert "re-onboard" in conflict["reason"]
    # recorded, and pullable afterwards
    listed = lineup.list_runs(db, "acc-1")
    assert listed["count"] == 1
    assert listed["runs"][0]["status"] == "auth_error"
    assert listed["runs"][0]["conflicts"][0]["kind"] == "auth"


def test_missing_schedule_block_fails_the_run():
    payload = _full_coverage_payload()
    del payload["proGamesByScoringPeriod"]
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client)
    assert run["status"] == "error"
    assert "proGamesByScoringPeriod" in run["error"]
    assert client.posts == []


# --- run log: tenant isolation + filters ------------------------------------------


def test_run_log_tenant_isolation_and_period_filter():
    db = FakeSupabase()
    client = StatefulClient(_full_coverage_payload())
    lineup.run_lineup(db, dict(ACCOUNT), client)
    other = dict(ACCOUNT, id="acc-2")
    lineup.run_lineup(db, other, StatefulClient(_full_coverage_payload()))

    mine = lineup.list_runs(db, "acc-1")
    assert mine["count"] == 1
    theirs = lineup.list_runs(db, "acc-2")
    assert theirs["count"] == 1
    # each account sees only its own run
    assert [r["id"] for r in mine["runs"]] == ["run-1"]
    assert [r["id"] for r in theirs["runs"]] == ["run-2"]

    assert lineup.list_runs(db, "acc-1", scoring_period_id=PERIOD)["count"] == 1
    assert lineup.list_runs(db, "acc-1", scoring_period_id=999)["count"] == 0
    assert lineup.list_runs(db, "nobody")["count"] == 0
    with pytest.raises(ValueError):
        lineup.list_runs(db, "acc-1", limit=0)
    with pytest.raises(ValueError):
        lineup.list_runs(db, "acc-1", limit=201)


# --- date -> scoring period resolution ----------------------------------------------

MS_OCT21_7PM_ET = int(
    datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc).timestamp() * 1000
)


def test_resolve_scoring_period():
    payload = _payload(
        [], {1: _games(1, 2, date_ms=MS_OCT21_7PM_ET)}, current=1
    )
    assert lineup.resolve_scoring_period(payload) == 1
    assert lineup.resolve_scoring_period(payload, date="2026-10-21") == 1
    # Monday 2026-10-26 is five days after the Oct 21 anchor period
    assert lineup.resolve_scoring_period(payload, date="2026-10-26") == 6
    # an explicit period always wins over a date
    assert (
        lineup.resolve_scoring_period(
            payload, date="2026-10-26", scoring_period_id=9
        )
        == 9
    )
    with pytest.raises(ValueError):
        lineup.resolve_scoring_period(payload, date="2026-10-01")
    with pytest.raises(ValueError):
        lineup.resolve_scoring_period(payload, date="10/26/2026")


def test_adhoc_run_for_future_date():
    payload = _full_coverage_payload(period=6)
    payload["status"]["currentScoringPeriod"] = 1
    payload["proGamesByScoringPeriod"]["1"] = _games(
        1, 2, date_ms=MS_OCT21_7PM_ET
    )
    db = FakeSupabase()
    client = StatefulClient(payload)
    run = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26")
    assert run["status"] == "ok"
    assert run["scoring_period_id"] == 6
    assert run["plan"]["requested"] == {
        "date": "2026-10-26",
        "scoring_period_id": None,
    }
    (post,) = client.posts
    assert post["scoring_period_id"] == 6
    # per-period idempotency: the same future day again is a noop
    again = lineup.run_lineup(db, dict(ACCOUNT), client, date="2026-10-26")
    assert again["status"] == "noop"
    assert len(client.posts) == 1


# --- player value ---------------------------------------------------------------------


def test_player_value_prefers_day_projection_then_last7():
    items = [{"stat_id": 0, "points": 1.0}]
    player = {
        "stats": [
            {"statSourceId": 0, "statSplitTypeId": 2, "appliedTotal": 70.0},
            {
                "statSourceId": 1,
                "statSplitTypeId": 5,
                "scoringPeriodId": PERIOD,
                "appliedTotal": 33.0,
            },
        ]
    }
    assert lineup.player_value(player, items, PERIOD) == (33.0, "day_projection")
    player["stats"] = player["stats"][:1]
    assert lineup.player_value(player, items, PERIOD) == (10.0, "recent7")
    # raw stat lines are scored with the league's own items when ESPN
    # did not pre-apply a total
    player["stats"] = [
        {
            "statSourceId": 1,
            "statSplitTypeId": 5,
            "scoringPeriodId": PERIOD,
            "stats": {"0": 21.0},
        }
    ]
    value, source = lineup.player_value(
        player, [{"stat_id": 0, "points": 2.0}], PERIOD
    )
    assert (value, source) == (42.0, "day_projection")


# --- write client (stubbed urlopen) ---------------------------------------------------


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)


class FakeHTTPResponse:
    def __init__(self, payload):
        if isinstance(payload, bytes):
            self._raw = payload
        elif isinstance(payload, str):
            self._raw = payload.encode("utf-8")
        else:
            self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(url, code, body=b"{}"):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


class StubTransport:
    def __init__(self, monkeypatch):
        self.requests = []
        self.handlers = {}
        monkeypatch.setattr(urllib.request, "urlopen", self._urlopen)

    def on(self, url_prefix, handler):
        self.handlers[url_prefix] = handler
        return self

    def _urlopen(self, req, timeout=None):
        self.requests.append(req)
        for prefix, handler in self.handlers.items():
            if req.full_url.startswith(prefix):
                return handler(req)
        raise AssertionError(f"unexpected URL: {req.full_url}")


def _ok(payload):
    return lambda req: FakeHTTPResponse(payload)


def _fail(code, body=b"{}"):
    return lambda req: (_ for _ in ()).throw(
        _http_error(req.full_url, code, body)
    )


LEAGUE_ID = 1709148631
SEASON = 2027
READ_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
    f"/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
)
WRITE_URL = (
    "https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba"
    f"/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}/transactions/"
)


def _wire_client():
    return EspnClient("s2-token", SWID, LEAGUE_ID, SEASON)


def test_transactions_url_and_post_payload(monkeypatch):
    t = StubTransport(monkeypatch).on(
        WRITE_URL, _ok({"status": "EXECUTED", "id": "txn-1"})
    )
    client = _wire_client()
    assert client.transactions_url() == WRITE_URL
    result = client.post_lineup_transaction(
        member_id=SWID,
        team_id=7,
        scoring_period_id=PERIOD,
        items=[{"playerId": 1, "fromLineupSlotId": BE, "toLineupSlotId": PG}],
    )
    assert result["status"] == "EXECUTED"
    (req,) = t.requests
    assert req.full_url == WRITE_URL
    assert req.get_method() == "POST"
    body = json.loads(req.data.decode("utf-8"))
    assert body["type"] == "ROSTER"
    assert body["isLeagueManager"] is False
    assert body["memberId"] == SWID
    assert body["teamId"] == 7
    assert body["scoringPeriodId"] == PERIOD
    assert body["items"] == [
        {
            "playerId": 1,
            "type": "LINEUP",
            "fromLineupSlotId": BE,
            "toLineupSlotId": PG,
        }
    ]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["cookie"] == f"espn_s2=s2-token; SWID={SWID}"


def test_post_401_and_html_login_raise_auth_error(monkeypatch):
    StubTransport(monkeypatch).on(WRITE_URL, _fail(401))
    with pytest.raises(EspnAuthError):
        _wire_client().post_lineup_transaction(
            member_id=SWID, team_id=7, scoring_period_id=PERIOD, items=[]
        )
    StubTransport(monkeypatch).on(
        WRITE_URL, _ok("<html><title>ESPN Login</title></html>")
    )
    with pytest.raises(EspnAuthError):
        _wire_client().post_lineup_transaction(
            member_id=SWID, team_id=7, scoring_period_id=PERIOD, items=[]
        )


def test_post_500_raises_error_with_status(monkeypatch):
    StubTransport(monkeypatch).on(WRITE_URL, _fail(500, b"boom"))
    with pytest.raises(EspnError) as excinfo:
        _wire_client().post_lineup_transaction(
            member_id=SWID, team_id=7, scoring_period_id=PERIOD, items=[]
        )
    assert excinfo.value.status == 500
    assert not isinstance(excinfo.value, EspnAuthError)


def test_get_league_scoping_param(monkeypatch):
    t = StubTransport(monkeypatch).on(READ_URL, _ok({"id": LEAGUE_ID}))
    client = _wire_client()
    client.get_league(["mRoster"], scoring_period_id=7)
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(t.requests[0].full_url).query
    )
    assert query == {"view": ["mRoster"], "scoringPeriodId": ["7"]}
    client.get_league(["mRoster"])
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(t.requests[1].full_url).query
    )
    assert query == {"view": ["mRoster"]}


# --- HTTP routes ------------------------------------------------------------------------


@pytest.fixture()
def lineup_app(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router, prefix="/espn")
    db = FakeSupabase()
    application.state.supabase = db
    client = StatefulClient(_full_coverage_payload())
    toggles = {}

    def fake_get_account(supabase, token):
        if token == "good-token":
            return dict(ACCOUNT)
        raise AccountError("invalid token")

    def fake_set_automation(supabase, account_id, enabled):
        toggles[account_id] = enabled
        return enabled

    monkeypatch.setattr(
        routes.accounts, "get_account_by_token", fake_get_account
    )
    monkeypatch.setattr(
        routes.accounts, "make_client_for_account", lambda account: client
    )
    monkeypatch.setattr(
        routes.accounts, "set_lineup_automation", fake_set_automation
    )
    return application, client, db, toggles


def _auth(token="good-token"):
    return {"Authorization": f"Bearer {token}"}


def test_automation_toggle_route(lineup_app):
    application, _client, _db, toggles = lineup_app
    http = TestClient(application)
    r = http.post(
        "/espn/automation/lineup", json={"enabled": True}, headers=_auth()
    )
    assert r.status_code == 200
    assert r.json() == {"lineup_automation_enabled": True}
    assert toggles == {"acc-1": True}
    r = http.post(
        "/espn/automation/lineup", json={"enabled": False}, headers=_auth()
    )
    assert r.json() == {"lineup_automation_enabled": False}
    r = http.post("/espn/automation/lineup", json={"enabled": True})
    assert r.status_code == 401


def test_run_and_runs_routes(lineup_app):
    application, client, _db, _toggles = lineup_app
    http = TestClient(application)

    r = http.post(
        "/espn/lineup/run", json={"dry_run": True}, headers=_auth()
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dry_run"
    assert client.posts == []

    r = http.post("/espn/lineup/run", json={}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert len(client.posts) == 1

    r = http.get("/espn/lineup/runs", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["runs"][0]["status"] == "ok"  # newest first
    assert body["runs"][1]["status"] == "dry_run"

    r = http.get(
        f"/espn/lineup/runs?scoring_period_id={PERIOD}", headers=_auth()
    )
    assert r.json()["count"] == 2
    r = http.get("/espn/lineup/runs?scoring_period_id=999", headers=_auth())
    assert r.json()["count"] == 0
    r = http.get("/espn/lineup/runs?limit=0", headers=_auth())
    assert r.status_code == 400
    r = http.get("/espn/lineup/runs")
    assert r.status_code == 401


def test_run_route_bad_date_is_400(lineup_app):
    application, _client, _db, _toggles = lineup_app
    http = TestClient(application)
    r = http.post(
        "/espn/lineup/run", json={"date": "10/26/2026"}, headers=_auth()
    )
    assert r.status_code == 400


# --- MCP tools ----------------------------------------------------------------------------


def test_mcp_run_lineup_and_get_lineup_runs(monkeypatch):
    from espn import mcp_server

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    db = FakeSupabase()
    client = StatefulClient(_full_coverage_payload())
    monkeypatch.setattr(mcp_server, "create_client", lambda url, key: db)

    def fake_get_account(supabase, token):
        if token == "cce_test":
            return dict(ACCOUNT)
        raise AccountError("invalid token")

    monkeypatch.setattr(
        mcp_server.accounts, "get_account_by_token", fake_get_account
    )
    monkeypatch.setattr(
        mcp_server.accounts,
        "make_client_for_account",
        lambda account: client,
    )

    names = sorted(t.name for t in mcp_server.mcp._tool_manager.list_tools())
    assert "run_lineup" in names
    assert "get_lineup_runs" in names

    def call(tool, args):
        return asyncio.run(mcp_server.mcp._tool_manager.call_tool(tool, args))

    out = json.loads(
        call("run_lineup", {"api_token": "cce_test", "dry_run": True})
    )
    assert out["status"] == "dry_run"
    assert client.posts == []

    out = json.loads(call("run_lineup", {"api_token": "cce_test"}))
    assert out["status"] == "ok"
    assert len(client.posts) == 1

    out = json.loads(call("get_lineup_runs", {"api_token": "cce_test"}))
    assert out["count"] == 2
    out = json.loads(
        call(
            "get_lineup_runs",
            {"api_token": "cce_test", "scoring_period_id": 999},
        )
    )
    assert out["count"] == 0
