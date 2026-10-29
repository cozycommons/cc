"""Unit + route tests for the ESPN waiver-wire report (espn/waivers.py).

Fixtures are hand-built ESPN v3-shaped payloads. Fantasy points are
computed from RAW stat lines through the league's scoring items (the
period-scoped stat entries deliberately carry no appliedTotal, so the
shared raw-stat conversion in lineup._applied_total is what runs).

Fixture scoring map (stat ids are fixture-local but consistent):
  FGM 3 (+2), FGA 4 (-1), FTM 5 (+1), FTA 6 (-1), 3PM 7 (+1),
  REB 10 (+1), AST 11 (+2), STL 12 (+4), BLK 13 (+4), TO 14 (-2),
  PTS 15 (+1)

Hand-computed spot checks (see test_fp_spot_checks):
  SPOT_1: FGM 8, FGA 14, FTM 5, FTA 6, 3PM 3, REB 7, AST 9, STL 2,
          BLK 1, TO 3, PTS 24
          = 16 - 14 + 5 - 6 + 3 + 7 + 18 + 8 + 4 - 6 + 24 = 59.0
  SPOT_2: FGM 4, FGA 10, FTM 2, FTA 2, 3PM 1, REB 4, AST 3, STL 0,
          BLK 0, TO 5, PTS 11
          = 8 - 10 + 2 - 2 + 1 + 4 + 6 + 0 + 0 - 10 + 11 = 10.0
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import routes, waivers
from espn.accounts import AccountError
from espn.espn_client import EspnAuthError, EspnError

CURRENT = 20  # current scoring period; last15 = 6..20, last7 = 14..20

SCORING_ITEMS = [
    {"statId": 3, "points": 2.0},    # FGM
    {"statId": 4, "points": -1.0},   # FGA
    {"statId": 5, "points": 1.0},    # FTM
    {"statId": 6, "points": -1.0},   # FTA
    {"statId": 7, "points": 1.0},    # 3PM
    {"statId": 10, "points": 1.0},   # REB
    {"statId": 11, "points": 2.0},   # AST
    {"statId": 12, "points": 4.0},   # STL
    {"statId": 13, "points": 4.0},   # BLK
    {"statId": 14, "points": -2.0},  # TO
    {"statId": 15, "points": 1.0},   # PTS
]

SPOT_1 = {"3": 8, "4": 14, "5": 5, "6": 6, "7": 3, "10": 7, "11": 9,
          "12": 2, "13": 1, "14": 3, "15": 24}
SPOT_2 = {"3": 4, "4": 10, "5": 2, "6": 2, "7": 1, "10": 4, "11": 3,
          "12": 0, "13": 0, "14": 5, "15": 11}


def _pts_game(fp):
    """A raw stat line worth exactly ``fp`` fantasy points (PTS only)."""
    return {"15": float(fp)}


# player_id -> {scoring_period: raw stat line}
GAME_LOG = {
    201: {8: _pts_game(40), 10: _pts_game(42), 12: _pts_game(38),
          16: _pts_game(44), 18: _pts_game(41), 20: SPOT_1},
    202: {7: _pts_game(30), 11: _pts_game(30), 15: _pts_game(30),
          19: _pts_game(30)},
    203: {8: _pts_game(20), 12: _pts_game(22), 15: _pts_game(20),
          18: _pts_game(21), 19: SPOT_2, 20: _pts_game(26)},
    204: {7: _pts_game(5), 9: _pts_game(5), 11: _pts_game(5),
          17: _pts_game(52), 19: _pts_game(52), 20: _pts_game(52)},
    205: {6: _pts_game(5), 10: _pts_game(5)},
    208: {9: _pts_game(8), 13: _pts_game(8)},
    209: {8: _pts_game(12), 12: _pts_game(12)},
    210: {7: _pts_game(3)},
    207: {15: _pts_game(60), 18: _pts_game(60), 20: _pts_game(60)},
    101: {15: _pts_game(45), 18: _pts_game(45), 20: _pts_game(45)},
    102: {16: _pts_game(6), 19: _pts_game(6)},
    103: {14: _pts_game(15), 17: _pts_game(15)},
    104: {18: _pts_game(2)},
    106: {15: _pts_game(9), 20: _pts_game(9)},
    107: {16: _pts_game(12), 19: _pts_game(12)},
    108: {17: _pts_game(18), 20: _pts_game(18)},
    109: {15: _pts_game(10.5), 18: _pts_game(10.5)},
    110: {16: _pts_game(11), 19: _pts_game(11)},
}


def _pool_player(pid, name, pos, pro_team, *, injury="ACTIVE",
                 owned=None, change=None, season_total=None,
                 season_avg=None, slots=None):
    stats = []
    if season_total is not None:
        entry = {"statSourceId": 0, "statSplitTypeId": 1,
                 "scoringPeriodId": 0, "appliedTotal": season_total}
        if season_avg is not None:
            entry["appliedAverage"] = season_avg
        stats.append(entry)
    player = {
        "id": pid,
        "fullName": name,
        "defaultPositionId": pos,
        "eligibleSlots": slots if slots is not None else [pos, 11],
        "proTeamId": pro_team,
        "injuryStatus": injury,
        "stats": stats,
    }
    if owned is not None:
        player["ownership"] = {"percentOwned": owned,
                               "percentChange": change}
    return player


POOL_PLAYERS = {
    # free agents
    201: _pool_player(201, "Breakout Bob", 0, 5, owned=12.0, change=2.5,
                      season_total=800.0, season_avg=20.0,
                      slots=[0, 5, 11, 12]),
    202: _pool_player(202, "Steady Vet", 4, 2, owned=45.0, change=0.4,
                      season_total=560.0, season_avg=28.0),
    203: _pool_player(203, "Schedule Stu", 1, 9, owned=8.0, change=0.0,
                      season_total=340.0, season_avg=17.0),
    204: _pool_player(204, "Hot Hand", 2, 14, owned=15.0, change=5.0,
                      season_total=480.0, season_avg=24.0),
    205: _pool_player(205, "Ice Cold", 3, 16, owned=5.0, change=-1.0,
                      season_total=120.0, season_avg=6.0),
    206: _pool_player(206, "Ghost", 0, 16, owned=2.0, change=0.0,
                      season_total=50.0, season_avg=5.0),
    208: _pool_player(208, "Deep Dan", 4, 16, owned=10.0, change=0.0,
                      season_total=180.0, season_avg=9.0),
    209: _pool_player(209, "Fringe Fred", 1, 16, owned=18.0, change=0.0,
                      season_total=200.0, season_avg=None),
    210: _pool_player(210, "Deep Deep", 2, 16, owned=3.0, change=0.0,
                      season_total=80.0, season_avg=4.0),
    # rostered elsewhere
    207: _pool_player(207, "Rival Star", 0, 2, owned=99.0, change=0.0,
                      season_total=1200.0, season_avg=60.0),
    # the account's own team
    101: _pool_player(101, "Star", 0, 5, season_total=900.0, season_avg=45.0),
    102: _pool_player(102, "Slumping Sam", 1, 5, season_total=200.0,
                      season_avg=10.0),
    103: _pool_player(103, "Mid", 2, 5, season_total=400.0, season_avg=20.0),
    104: _pool_player(104, "Out Oliver", 3, 5, injury="OUT",
                      season_total=100.0, season_avg=8.0),
    105: _pool_player(105, "IR Ivan", 4, 5, injury="INJURY_RESERVE",
                      season_total=90.0, season_avg=9.0),
    106: _pool_player(106, "Bench Bob", 1, 5, season_total=220.0,
                      season_avg=11.0),
    107: _pool_player(107, "Meh Mike", 2, 5, season_total=300.0,
                      season_avg=15.0),
    108: _pool_player(108, "Okay Kay", 3, 5, season_total=420.0,
                      season_avg=21.0),
    109: _pool_player(109, "Low Lou", 4, 5, season_total=260.0,
                      season_avg=13.0),
    110: _pool_player(110, "Quiet Quinn", 0, 5, season_total=280.0,
                      season_avg=14.0),
}

OWN_ROSTER_IDS = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]


def _roster_entry(pid, slot=12):
    return {
        "playerId": pid,
        "lineupSlotId": slot,
        "playerPoolEntry": {"player": {"id": pid,
                                       "fullName": POOL_PLAYERS[pid]["fullName"],
                                       "injuryStatus": POOL_PLAYERS[pid]["injuryStatus"],
                                       "proTeamId": POOL_PLAYERS[pid]["proTeamId"]}},
    }


def _games_block():
    # period -> [(home, away)]; team 5 plays 5x, team 9 plays 5x,
    # team 14 plays 3x, team 16 plays 3x, team 2 plays 2x in 21..27.
    slate = {
        21: [(5, 2), (9, 16)],
        22: [(9, 14)],
        23: [(16, 5)],
        24: [(2, 9), (14, 16)],
        25: [(5, 9)],
        26: [(9, 5)],
        27: [(14, 5)],
    }
    block = {}
    for period, games in slate.items():
        block[str(period)] = [
            {"date": 1793000000000 + period * 86400000,
             "homeProTeamId": home, "awayProTeamId": away}
            for home, away in games
        ]
    return block


LEAGUE_PAYLOAD = {
    "id": 123456,
    "seasonId": 2027,
    "settings": {
        "name": "Fantasy Hoops '27",
        "size": 12,
        "scoringSettings": {"scoringItems": SCORING_ITEMS},
    },
    "status": {"currentMatchupPeriod": 3, "currentScoringPeriod": CURRENT,
               "firstScoringPeriod": 1},
    "members": [{"id": "{SWID-1}", "displayName": "Warner"},
                {"id": "m2", "displayName": "Rival"}],
    "teams": [
        {
            "id": 1, "abbrev": "MINE", "name": "mr diddles",
            "owners": ["{SWID-1}"],
            "roster": {"entries": [
                _roster_entry(pid, 13 if pid == 105 else 12)
                for pid in OWN_ROSTER_IDS
            ]},
        },
        {
            "id": 2, "abbrev": "RIV", "name": "Rivals",
            "owners": ["m2"],
            "roster": {"entries": [_roster_entry(207)]},
        },
    ],
    "proGamesByScoringPeriod": _games_block(),
}


class FakeClient:
    league_id = 123456
    season = 2027

    def __init__(self, *, fail_periods=(), auth_fail=False, strip_ownership=False):
        self.fail_periods = set(fail_periods)
        self.auth_fail = auth_fail
        self.strip_ownership = strip_ownership

    def get_league(self, views):
        return LEAGUE_PAYLOAD

    def get_players(self, limit=300):
        entries = []
        for pid, player in POOL_PLAYERS.items():
            player = dict(player)
            if self.strip_ownership:
                player.pop("ownership", None)
            entry = {"id": pid, "player": player}
            if pid in OWN_ROSTER_IDS:
                entry["onTeamId"] = 1
            elif pid == 207:
                entry["onTeamId"] = 2
            elif pid % 2 == 0:
                entry["onTeamId"] = 0
            entries.append(entry)
        return entries

    def get_players_for_period(self, scoring_period_id, limit=1000):
        if self.auth_fail:
            raise EspnAuthError("cookies expired")
        if scoring_period_id in self.fail_periods:
            raise EspnError("boom")
        entries = []
        for pid, games in GAME_LOG.items():
            raw = games.get(scoring_period_id)
            if raw is None:
                continue
            entries.append({
                "id": pid,
                "player": {
                    "id": pid,
                    "stats": [{
                        "statSourceId": 0,
                        "statSplitTypeId": 0,
                        "scoringPeriodId": scoring_period_id,
                        "stats": raw,
                    }],
                },
            })
        return entries


def _report(client=None):
    return waivers.get_waivers(client or FakeClient(), "{SWID-1}")


def _by_id(players):
    return {p["player_id"]: p for p in players}


# --- the FP spot checks ---------------------------------------------------------


def test_fp_spot_checks():
    """Hand-computed FP from raw stats must match the shared conversion."""
    items = [{"stat_id": i["statId"], "points": i["points"]}
             for i in SCORING_ITEMS]
    entry1 = {"statSourceId": 0, "statSplitTypeId": 0,
              "scoringPeriodId": 20, "stats": SPOT_1}
    entry2 = {"statSourceId": 0, "statSplitTypeId": 0,
              "scoringPeriodId": 19, "stats": SPOT_2}
    from espn import lineup
    assert lineup._applied_total(entry1, items) == 59.0
    assert lineup._applied_total(entry2, items) == 10.0
    # and through the waivers day-extraction path
    player = {"stats": [entry1]}
    assert waivers._day_fantasy_points(player, 20, items) == 59.0


# --- report behaviour -------------------------------------------------------------


def test_report_shape_and_free_agents():
    report = _report()
    assert report["league_id"] == 123456
    assert report["season"] == 2027
    assert report["scoring_period"] == CURRENT
    assert report["generated_at"].endswith("Z")

    free = report["free_agents"]
    # ranked by fp_pg_last15 desc; Ghost (0 games) and Rival Star
    # (rostered) are absent
    assert [p["player_id"] for p in free] == [
        201, 202, 204, 203, 209, 208, 205, 210
    ]
    bob = _by_id(free)[201]
    assert bob["name"] == "Breakout Bob"
    assert bob["pro_team"] == "CLE"
    assert bob["positions"] == ["PG", "G", "UTIL"]
    assert bob["ownership_pct"] == 12.0
    assert bob["ownership_change"] == 2.5
    assert bob["games_played_last15"] == 6
    assert bob["fp_pg_last15"] == 44.0
    assert bob["fp_pg_last7"] == 48.0
    assert bob["fp_pg_season"] == 20.0
    assert bob["fp_last3_games"] == [44.0, 41.0, 59.0]
    assert bob["games_next_7d"] == 5
    assert any("44.0 FP/g last 15 vs 20.0 season" in r for r in bob["reasons"])


def test_pocket_picks_rules():
    report = _report()
    picks = report["pocket_picks"]
    assert [p["player_id"] for p in picks] == [201, 204, 203]
    by_id = _by_id(picks)
    assert any("breakout" in r for r in by_id[201]["reasons"])
    assert any("scorching week" in r for r in by_id[204]["reasons"])
    assert any("schedule edge" in r for r in by_id[203]["reasons"])
    # Steady Vet: 45% owned and no qualifying rule -> not a pick
    assert 202 not in by_id


def test_drop_candidates_exclude_out_and_ir():
    report = _report()
    drops = report["drop_candidates"]
    assert [p["player_id"] for p in drops] == [102, 106, 109, 110, 107]
    notes = " ".join(report["notes"])
    assert "Out Oliver" in notes and "IR Ivan" in notes
    assert any("coldest on your roster" in r for r in drops[0]["reasons"])


def test_season_rate_fallback_is_disclosed():
    report = _report()
    fred = _by_id(report["free_agents"])[209]
    # no appliedAverage in the fixture: 200.0 season total / period 20
    assert fred["fp_pg_season"] == 10.0
    assert any("per-day rate" in n for n in report["notes"])


def test_ownership_absent_is_null_and_disclosed():
    report = _report(FakeClient(strip_ownership=True))
    bob = _by_id(report["free_agents"])[201]
    assert bob["ownership_pct"] is None
    assert bob["ownership_change"] is None
    assert any("ownership data absent" in n for n in report["notes"])
    # the ownership gate is skipped, so the breakout pick still lands
    assert 201 in _by_id(report["pocket_picks"])


def test_period_fetch_failures_degrade_with_notes():
    report = _report(FakeClient(fail_periods=range(6, CURRENT + 1)))
    assert report["free_agents"] == []
    assert any("whole window" in n for n in report["notes"])
    # drop candidates still rank, on the season fallback
    assert report["drop_candidates"]


def test_period_auth_failure_propagates():
    with pytest.raises(EspnAuthError):
        _report(FakeClient(auth_fail=True))


# --- route ------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router, prefix="/espn")
    application.state.supabase = object()

    def fake_get_account(supabase, token):
        if token == "good-token":
            return {"id": "acc-1", "label": "warner", "league_id": 123456,
                    "season": 2027, "espn_s2": "s2", "swid": "{SWID-1}",
                    "lineup_automation_enabled": False}
        raise AccountError("invalid token")

    monkeypatch.setattr(routes.accounts, "get_account_by_token",
                        fake_get_account)
    monkeypatch.setattr(routes.accounts, "make_client_for_account",
                        lambda account: FakeClient())
    return TestClient(application)


def test_waivers_route(client):
    r = client.get("/espn/waivers",
                   headers={"Authorization": "Bearer " + "good-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["scoring_period"] == CURRENT
    assert body["free_agents"][0]["player_id"] == 201
    assert body["pocket_picks"]
    assert body["drop_candidates"]


def test_waivers_route_requires_auth(client):
    r = client.get("/espn/waivers")
    assert r.status_code == 401
