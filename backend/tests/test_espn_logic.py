"""Unit tests for ESPN Fantasy logic: slimming, trends, and snapshot trends.

Fixtures are hand-built ESPN v3-shaped payloads (one merged league payload
registered for every view-set the logic requests) with hand-computed
expected values for standings, all-play wins, and trend rates.
"""

import pytest

from espn import logic


# --- fixture payloads ----------------------------------------------------------


def _player(pid, name, pos, *, pro_team=5, injury="ACTIVE", owned=None,
            started=None, change=None, season=None, recent7=None):
    stats = []
    if season is not None:
        stats.append(
            {"scoringPeriodId": 15, "statSplitTypeId": 1, "appliedTotal": season}
        )
    if recent7 is not None:
        stats.append(
            {"scoringPeriodId": 15, "statSplitTypeId": 2, "appliedTotal": recent7}
        )
    return {
        "id": pid,
        "fullName": name,
        "defaultPositionId": pos,
        "eligibleSlots": [pos, 11],
        "proTeamId": pro_team,
        "injuryStatus": injury,
        "ownership": {
            "percentOwned": owned,
            "percentChange": change,
            "percentStarted": started,
        },
        "stats": stats,
    }


def _roster_entry(player):
    return {
        "playerId": player["id"],
        "playerPoolEntry": {"player": player},
    }


_ROSTER_1 = _player(
    101, "Player One", 0, owned=90.5, started=80.0, change=1.2,
    season=250.0, recent7=35.0,
)
_ROSTER_1["eligibleSlots"] = [0, 5, 11]
_ROSTER_2 = _player(
    102, "Player Two", 4, pro_team=10, injury="OUT", owned=50.0,
    started=40.0, change=-0.5, season=180.0, recent7=14.0,
)
_ROSTER_2["eligibleSlots"] = [4, 9, 11]

LEAGUE_PAYLOAD = {
    "id": 123456,
    "seasonId": 2027,
    "settings": {
        "name": "Fantasy Hoops '27",
        "size": 3,
        "scoringSettings": {
            "scoringItems": [{"statId": 13, "points": 1.0}],
        },
    },
    "status": {
        "currentMatchupPeriod": 3,
        "currentScoringPeriod": 15,
        "firstScoringPeriod": 1,
    },
    "members": [
        {"id": "m1", "displayName": "Alice"},
        {"id": "m2", "displayName": "Bob"},
        {"id": "m3", "displayName": "Carol"},
    ],
    "teams": [
        {
            "id": 1,
            "abbrev": "ALP",
            "name": "Alpha",
            "owners": ["m1"],
            "record": {
                "overall": {
                    "wins": 8, "losses": 2, "ties": 0,
                    "pointsFor": 1000.5, "pointsAgainst": 900.0,
                    "streak": {"type": "WIN", "length": 2},
                }
            },
            "roster": {"entries": [_roster_entry(_ROSTER_1),
                                   _roster_entry(_ROSTER_2)]},
        },
        {
            "id": 2,
            "abbrev": "BET",
            "name": "Beta",
            "owners": ["m2"],
            "record": {
                "overall": {
                    "wins": 5, "losses": 5, "ties": 0,
                    "pointsFor": 950.0, "pointsAgainst": 920.0,
                    "streak": {"type": "LOSS", "length": 1},
                }
            },
            "roster": {"entries": []},
        },
        {
            # older payloads split the name into location + nickname
            "id": 3,
            "abbrev": "GAM",
            "location": "Gamma",
            "nickname": "Geckos",
            "owners": ["m3"],
            "record": {
                "overall": {
                    "wins": 5, "losses": 4, "ties": 1,
                    "pointsFor": 900.0, "pointsAgainst": 950.0,
                    "streak": {"type": "TIE", "length": 1},
                }
            },
            "roster": {"entries": []},
        },
    ],
    # weekly points: t1 {1: 100, 2: 110}, t2 {1: 90, 2: 105},
    # t3 {1: 80, 2: 105}; week 3 is unplayed (None totals).
    "schedule": [
        {"id": 1, "matchupPeriodId": 1,
         "home": {"teamId": 1, "totalPoints": 100.0},
         "away": {"teamId": 2, "totalPoints": 90.0}, "winner": "HOME"},
        {"id": 2, "matchupPeriodId": 1,
         "home": {"teamId": 3, "totalPoints": 80.0},
         "away": {"teamId": 1, "totalPoints": 100.0}, "winner": "AWAY"},
        {"id": 3, "matchupPeriodId": 2,
         "home": {"teamId": 1, "totalPoints": 110.0},
         "away": {"teamId": 3, "totalPoints": 105.0}, "winner": "HOME"},
        {"id": 4, "matchupPeriodId": 2,
         "home": {"teamId": 2, "totalPoints": 105.0},
         "away": {"teamId": 3, "totalPoints": 105.0}, "winner": "UNDECIDED"},
        {"id": 5, "matchupPeriodId": 3,
         "home": {"teamId": 1, "totalPoints": None},
         "away": {"teamId": 2, "totalPoints": None}, "winner": "UNDECIDED"},
        {"id": 6, "matchupPeriodId": 3,
         "home": {"teamId": 3, "totalPoints": None},
         "away": {"teamId": 2, "totalPoints": None}, "winner": "UNDECIDED"},
    ],
    "transactions": [
        {
            "id": "t-waiver", "type": "WAIVER", "status": "EXECUTED",
            "executionType": "EXECUTE", "memberId": "m2", "teamId": 2,
            "bidAmount": 15, "scoringPeriodId": 44,
            "date": 1700000000000,  # 2023-11-14T22:13:20Z
            "items": [
                {"type": "ADD", "playerId": 301, "fromTeamId": 0, "toTeamId": 2},
                {"type": "DROP", "playerId": 302, "fromTeamId": 2, "toTeamId": 0},
            ],
        },
        {
            "id": "t-old", "type": "FREEAGENT", "status": "EXECUTED",
            "executionType": "EXECUTE", "memberId": "m3", "teamId": 3,
            "bidAmount": None, "scoringPeriodId": 43,
            "date": 1699996400000,  # 2023-11-14T21:13:20Z
            "items": [
                {"type": "ADD", "playerId": 303, "fromTeamId": 0, "toTeamId": 3},
            ],
        },
        {
            "id": "t-trade", "type": "TRADE", "status": "EXECUTED",
            "executionType": "EXECUTE", "memberId": "m1", "teamId": 1,
            "bidAmount": None, "scoringPeriodId": 45,
            "date": 1700003600000,  # 2023-11-14T23:13:20Z
            "items": [
                {"type": "TRADE", "playerId": 201, "fromTeamId": 1, "toTeamId": 2},
                {"type": "TRADE", "playerId": 202, "fromTeamId": 2, "toTeamId": 1},
            ],
        },
    ],
    "draftDetail": {
        "drafted": True,
        "picks": [
            {"teamId": 3, "playerId": 203, "roundId": 1, "roundPickNumber": 3,
             "overallPickNumber": 3, "keeper": False, "bidAmount": None},
            {"teamId": 2, "playerId": 205, "roundId": 2, "roundPickNumber": 2,
             "overallPickNumber": 5, "keeper": True, "bidAmount": None},
            {"teamId": 1, "playerId": 201, "roundId": 1, "roundPickNumber": 1,
             "overallPickNumber": 1, "keeper": False, "bidAmount": None},
            {"teamId": 3, "playerId": 204, "roundId": 2, "roundPickNumber": 1,
             "overallPickNumber": 4, "keeper": False, "bidAmount": None},
            {"teamId": 2, "playerId": 202, "roundId": 1, "roundPickNumber": 2,
             "overallPickNumber": 2, "keeper": False, "bidAmount": None},
        ],
    },
}

KONA_PLAYERS = [
    {"id": 101, "onTeamId": 1, "player": _ROSTER_1},
    {"id": 102, "onTeamId": 1, "player": _ROSTER_2},
    {"id": 103, "onTeamId": 0,
     "player": _player(103, "Free Agent", 2, owned=10.0, started=5.0,
                       change=2.0, season=120.0)},
    {"id": 104, "onTeamId": 2,
     "player": _player(104, "Odd Position", 99, owned=30.0, started=25.0,
                       change=0.0, recent7=21.0)},
    {"id": 999, "onTeamId": 2},  # no player dict: skipped by build_snapshot
]

_VIEW_SETS = [
    ("mSettings", "mTeam"),
    ("mTeam", "mStandings"),
    ("mTeam", "mRoster"),
    ("mTransactions2",),
    ("mDraftDetail", "mTeam"),
    ("mTeam", "mMatchup"),
    ("mSettings", "mTeam", "mMatchup"),
]


class FakeClient:
    """Merged fixture payload registered for each view-set logic requests."""

    league_id = 123456
    season = 2027

    def __init__(self, payload=None, players=None):
        merged = LEAGUE_PAYLOAD if payload is None else payload
        self.league_payloads = {frozenset(v): merged for v in _VIEW_SETS}
        self._players = KONA_PLAYERS if players is None else players
        self.requested_views = []
        self.requested_player_limits = []

    def get_league(self, views):
        self.requested_views.append(tuple(views))
        return self.league_payloads[frozenset(views)]

    def get_players(self, limit=300):
        self.requested_player_limits.append(limit)
        return self._players


@pytest.fixture()
def client():
    return FakeClient()


# --- league / standings / teams -------------------------------------------------


def test_get_league(client):
    res = logic.get_league(client)
    assert res["league_id"] == 123456
    assert res["name"] == "Fantasy Hoops '27"
    assert res["season"] == 2027
    assert res["size"] == 3
    assert res["current_week"] == 3
    assert res["current_scoring_period"] == 15
    assert res["scoring_items"] == [{"statId": 13, "points": 1.0}]
    assert [t["team_id"] for t in res["teams"]] == [1, 2, 3]
    alpha = res["teams"][0]
    assert alpha["name"] == "Alpha"
    assert alpha["owner"] == "Alice"
    assert alpha["wins"] == 8
    assert alpha["points_for"] == 1000.5
    assert alpha["streak"] == "W2"
    # location + nickname fallback for the older team shape
    assert res["teams"][2]["name"] == "Gamma Geckos"
    assert res["teams"][2]["streak"] == "T1"


def test_get_league_acquisition_settings():
    settings = dict(LEAGUE_PAYLOAD["settings"])
    settings["acquisitionSettings"] = {
        "acquisitionLimit": -1,
        "acquisitionType": "WAIVERS",
        "acquisitionBudget": 100,
        "isUsingAcquisitionBudget": True,
        "minimumBid": 1,
        "waiverHours": 24,
        "waiverOrderReset": True,
    }
    settings["tradeSettings"] = {"deadlineDate": 1796000000000}
    payload = dict(LEAGUE_PAYLOAD, settings=settings)
    res = logic.get_league(FakeClient(payload=payload))
    assert res["acquisition_settings"] == {
        "acquisition_limit": -1,
        "acquisition_type": "WAIVERS",
        "acquisition_budget": 100,
        "is_using_acquisition_budget": True,
        "minimum_bid": 1,
        "waiver_hours": 24,
        "waiver_order_reset": True,
        "trade_deadline": 1796000000000,
    }
    # pre-existing keys are untouched
    assert res["name"] == "Fantasy Hoops '27"
    assert res["size"] == 3


def test_get_league_acquisition_settings_absent(client):
    # the default fixture carries no acquisitionSettings/tradeSettings
    # blocks: every field degrades to None instead of disappearing
    res = logic.get_league(client)
    assert res["acquisition_settings"] == {
        "acquisition_limit": None,
        "acquisition_type": None,
        "acquisition_budget": None,
        "is_using_acquisition_budget": None,
        "minimum_bid": None,
        "waiver_hours": None,
        "waiver_order_reset": None,
        "trade_deadline": None,
    }


def test_get_standings_order_and_rank(client):
    res = logic.get_standings(client)
    assert res["count"] == 3
    # wins desc, then points_for desc: Beta (5 wins, 950) edges Gamma (5, 900)
    assert [(s["team_id"], s["rank"]) for s in res["standings"]] == [
        (1, 1), (2, 2), (3, 3),
    ]
    assert res["standings"][1]["streak"] == "L1"


def test_get_team_roster_slimming(client):
    res = logic.get_team(client, 1)
    assert res["team"]["name"] == "Alpha"
    assert res["roster_count"] == 2
    one, two = res["roster"]
    assert one == {
        "player_id": 101,
        "name": "Player One",
        "position": "PG",
        "eligible_slots": ["PG", "G", "UTIL"],
        "pro_team_id": 5,
        "injury_status": "ACTIVE",
        "percent_owned": 90.5,
        "percent_change": 1.2,
    }
    assert two["position"] == "C"
    assert two["eligible_slots"] == ["C", "PF/C", "UTIL"]
    assert two["injury_status"] == "OUT"


def test_get_team_unknown_raises(client):
    with pytest.raises(ValueError, match="team not found"):
        logic.get_team(client, 99)


# --- transactions / draft ---------------------------------------------------------


def test_transactions_sorted_limit_and_shape(client):
    res = logic.get_transactions(client, limit=2)
    assert res["count"] == 2
    # newest first despite the payload being out of order
    assert [t["id"] for t in res["transactions"]] == ["t-trade", "t-waiver"]

    waiver = logic.get_transactions(client)["transactions"][1]
    assert waiver["date"] == "2023-11-14T22:13:20Z"
    assert waiver["type"] == "WAIVER"
    assert waiver["bid_amount"] == 15
    assert waiver["team_id"] == 2
    assert waiver["member_id"] == "m2"
    assert waiver["scoring_period_id"] == 44
    assert waiver["moves"] == [
        {"action": "ADD", "player_id": 301, "from_team_id": 0, "to_team_id": 2},
        {"action": "DROP", "player_id": 302, "from_team_id": 2, "to_team_id": 0},
    ]

    trade = logic.get_transactions(client)["transactions"][0]
    assert trade["date"] == "2023-11-14T23:13:20Z"
    assert [m["action"] for m in trade["moves"]] == ["TRADE", "TRADE"]


@pytest.mark.parametrize("bad", [0, -1, 201])
def test_transactions_limit_validation(client, bad):
    with pytest.raises(ValueError):
        logic.get_transactions(client, limit=bad)


def test_get_draft_sorted_with_team_names(client):
    res = logic.get_draft(client)
    assert res["drafted"] is True
    assert res["count"] == 5
    assert [p["overall_pick"] for p in res["picks"]] == [1, 2, 3, 4, 5]
    assert [p["player_id"] for p in res["picks"]] == [201, 202, 203, 204, 205]
    first = res["picks"][0]
    assert first["round"] == 1
    assert first["pick_in_round"] == 1
    assert first["team_name"] == "Alpha"
    assert res["picks"][2]["team_name"] == "Gamma Geckos"
    assert res["picks"][4]["keeper"] is True


# --- team trends ------------------------------------------------------------------


def test_team_trends_hand_computed(client):
    res = logic.get_team_trends(client)
    # sorted by total points_for desc
    assert [t["team_id"] for t in res["teams"]] == [1, 2, 3]
    by_id = {t["team_id"]: t for t in res["teams"]}

    alpha = by_id[1]
    assert alpha["points_by_week"] == {"1": 100.0, "2": 110.0}
    assert alpha["last3_avg"] == 105.0
    # beats both opponents both weeks: 1.0 + 1.0
    assert alpha["allplay_expected_wins"] == 2.0
    assert alpha["luck"] == 6.0  # 8 wins - 2.0
    assert alpha["total_points_for"] == 1000.5
    assert alpha["total_points_against"] == 900.0
    assert alpha["streak"] == "W2"

    beta = by_id[2]
    assert beta["points_by_week"] == {"1": 90.0, "2": 105.0}
    assert beta["last3_avg"] == 97.5
    # w1: 1 of 2 opponents lower -> 0.5; w2: 0 lower + 1 tie -> 0.25
    assert beta["allplay_expected_wins"] == 0.75
    assert beta["luck"] == 4.25  # 5 - 0.75

    gamma = by_id[3]
    assert gamma["points_by_week"] == {"1": 80.0, "2": 105.0}
    assert gamma["last3_avg"] == 92.5
    # w1: 0; w2: 0 lower + 1 tie -> 0.25
    assert gamma["allplay_expected_wins"] == 0.25
    assert gamma["luck"] == 4.75  # 5 - 0.25


# --- snapshots ---------------------------------------------------------------------


def test_build_snapshot_shape(client):
    snap = logic.build_snapshot(client)
    assert snap["league_id"] == 123456
    assert snap["season"] == 2027
    assert snap["name"] == "Fantasy Hoops '27"
    assert snap["current_scoring_period"] == 15
    assert snap["current_matchup_period"] == 3
    assert client.requested_player_limits == [300]

    by_id = {t["team_id"]: t for t in snap["teams"]}
    assert by_id[1]["weekly_points"] == {"1": 100.0, "2": 110.0}
    assert by_id[1]["wins"] == 8
    assert by_id[3]["name"] == "Gamma Geckos"

    # the entry without a player dict is skipped
    assert [p["player_id"] for p in snap["players"]] == [101, 102, 103, 104]
    players = {p["player_id"]: p for p in snap["players"]}
    assert players[101]["season_fantasy_points"] == 250.0
    assert players[101]["recent7_fantasy_points"] == 35.0
    assert players[101]["percent_started"] == 80.0
    assert players[101]["team_id"] == 1
    # free agent (onTeamId 0) -> team_id None; missing split -> None
    assert players[103]["team_id"] is None
    assert players[103]["season_fantasy_points"] == 120.0
    assert players[103]["recent7_fantasy_points"] is None
    assert players[104]["season_fantasy_points"] is None
    assert players[104]["recent7_fantasy_points"] == 21.0
    # unknown position id falls back to POS<id>
    assert players[104]["position"] == "POS99"


# --- player trends over snapshots ---------------------------------------------------


def _snap_player(pid, name="P", team_id=1, owned=None, change=None,
                 season=None, recent7=None):
    return {
        "player_id": pid,
        "name": name,
        "team_id": team_id,
        "percent_owned": owned,
        "percent_started": None,
        "percent_change": change,
        "season_fantasy_points": season,
        "recent7_fantasy_points": recent7,
    }


def _snap(players, period=14):
    return {
        "league_id": 123456,
        "season": 2027,
        "name": "Fantasy Hoops '27",
        "current_scoring_period": period,
        "current_matchup_period": 2,
        "teams": [],
        "players": players,
    }


def test_ownership_trends_snapshot_path():
    current = _snap([
        _snap_player(1, "Riser", owned=80.0),
        _snap_player(2, "Faller", owned=40.0),
        _snap_player(3, "Flat", owned=20.0),
        _snap_player(4, "New", owned=90.0),      # absent previously: excluded
        _snap_player(5, "Big Faller", owned=10.0),
    ])
    previous = _snap([
        _snap_player(1, owned=60.0),
        _snap_player(2, owned=55.0),
        _snap_player(3, owned=20.0),
        _snap_player(5, owned=30.0),
        _snap_player(6, owned=99.0),            # absent now: excluded
    ])
    res = logic.player_ownership_trends(current, previous)
    assert res["source"] == "snapshots"
    assert res["most_added"] == [
        {"player_id": 1, "name": "Riser", "team_id": 1,
         "percent_owned": 80.0, "ownership_change": 20.0},
    ]
    # most negative first
    assert [p["player_id"] for p in res["most_dropped"]] == [5, 2]
    assert [p["ownership_change"] for p in res["most_dropped"]] == [-20.0, -15.0]

    limited = logic.player_ownership_trends(current, previous, limit=1)
    assert [p["player_id"] for p in limited["most_dropped"]] == [5]


def test_ownership_trends_fallback_uses_percent_change():
    current = _snap([
        _snap_player(1, "Up", owned=80.0, change=3.5),
        _snap_player(2, "Down", owned=40.0, change=-2.0),
        _snap_player(3, "Flat", owned=20.0, change=0.0),
        _snap_player(4, "Unknown", owned=10.0, change=None),
    ])
    res = logic.player_ownership_trends(current, None)
    assert res["source"] == "espn_percent_change"
    assert [p["player_id"] for p in res["most_added"]] == [1]
    assert res["most_added"][0]["ownership_change"] == 3.5
    assert [p["player_id"] for p in res["most_dropped"]] == [2]
    assert res["most_dropped"][0]["ownership_change"] == -2.0


def test_performance_trends_snapshot_path():
    current = _snap([
        _snap_player(1, "Hot", season=210.0),
        _snap_player(2, "Cold", season=70.0),
        _snap_player(3, "Steady", season=140.0),
        _snap_player(4, "New", season=50.0),     # absent previously: excluded
    ], period=14)
    previous = _snap([
        _snap_player(1, season=70.0),
        _snap_player(2, season=63.0),
        _snap_player(3, season=70.0),
    ], period=7)
    res = logic.player_performance_trends(current, previous, span_days=7)
    assert res["source"] == "snapshots"
    # Hot: recent (210-70)/7 = 20/day vs season 210/14 = 15/day -> +5
    assert res["risers"] == [
        {"player_id": 1, "name": "Hot", "team_id": 1,
         "season_fantasy_points": 210.0, "recent_points_per_day": 20.0,
         "season_points_per_day": 15.0, "delta_per_day": 5.0},
    ]
    # Cold: recent (70-63)/7 = 1/day vs season 70/14 = 5/day -> -4
    # Steady: recent 10/day vs season 10/day -> delta 0, excluded
    assert res["fallers"] == [
        {"player_id": 2, "name": "Cold", "team_id": 1,
         "season_fantasy_points": 70.0, "recent_points_per_day": 1.0,
         "season_points_per_day": 5.0, "delta_per_day": -4.0},
    ]


def _splits_current():
    return _snap([
        _snap_player(1, "Hot", season=100.0, recent7=105.0),
        _snap_player(2, "Cold", season=200.0, recent7=70.0),
        _snap_player(3, "NoSplit", season=50.0, recent7=None),
    ], period=10)


def test_performance_trends_splits_fallback():
    res = logic.player_performance_trends(_splits_current(), None)
    assert res["source"] == "espn_splits"
    # Hot: recent 105/7 = 15/day vs season 100/10 = 10/day -> +5
    assert [p["player_id"] for p in res["risers"]] == [1]
    assert res["risers"][0]["delta_per_day"] == 5.0
    # Cold: recent 70/7 = 10/day vs season 200/10 = 20/day -> -10
    assert [p["player_id"] for p in res["fallers"]] == [2]
    assert res["fallers"][0]["delta_per_day"] == -10.0


def test_performance_trends_fresh_previous_falls_back_to_splits():
    previous = _snap([_snap_player(1, season=10.0)], period=9)
    res = logic.player_performance_trends(
        _splits_current(), previous, span_days=0.5
    )
    assert res["source"] == "espn_splits"
    assert [p["player_id"] for p in res["risers"]] == [1]


def test_performance_trends_insufficient_history():
    current = _snap([
        _snap_player(1, season=None, recent7=None),
        _snap_player(2, season=50.0, recent7=None),
    ])
    res = logic.player_performance_trends(current, None)
    assert res == {"risers": [], "fallers": [], "source": "insufficient_history"}
