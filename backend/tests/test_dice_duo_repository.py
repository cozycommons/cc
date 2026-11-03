from datetime import datetime, timezone

from dice import duo_repository
from dice.duo_rating import DuoMatch, DuoRatingState, canonical_duo_id


ALPHA = "u-alpha"
BRAVO = "u-bravo"
CHARLIE = "u-charlie"
DELTA = "u-delta"


def _matches():
    return [
        DuoMatch(
            game_id=f"game-{index}",
            played_at=datetime(2026, 1, index, tzinfo=timezone.utc),
            team1=(ALPHA, BRAVO),
            team2=(CHARLIE, DELTA),
            winner_team=1 if index < 4 else 2,
            team1_score=11 if index < 4 else 8,
            team2_score=8 if index < 4 else 11,
        )
        for index in range(1, 6)
    ]


def _profiles():
    return [
        {"user_id": ALPHA, "display_name": "Alpha Toss", "avatar_url": "/alpha.webp"},
        {"user_id": BRAVO, "display_name": "Bravo Catch", "avatar_url": "/bravo.webp"},
        {"user_id": CHARLIE, "display_name": "Charlie Sink", "avatar_url": None},
        {"user_id": DELTA, "display_name": "Delta Dink", "avatar_url": None},
    ]


def test_list_ladder_maps_replayed_state_to_profile_summaries(monkeypatch):
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (_profiles(), _matches()))

    ladder = duo_repository.list_duo_ladder(object())

    assert ladder.ranked[0].duo_id == canonical_duo_id(ALPHA, BRAVO)
    assert ladder.ranked[0].members[0].display_name == "Alpha Toss"
    assert ladder.ranked[0].games == 5
    assert ladder.ranked[0].homepage_eligible is True
    assert ladder.to_watch == []


def test_competition_ranks_use_elo_and_preserve_ties():
    states = [
        DuoRatingState("first-a", ("a", "b"), elo=1579, deviation=200, ranked_games=3),
        DuoRatingState("first-b", ("c", "d"), elo=1579, deviation=50, ranked_games=5),
        DuoRatingState("third", ("e", "f"), elo=1520, deviation=20, ranked_games=8),
    ]

    assert duo_repository._competition_ranks(states) == {
        "first-a": 1, "first-b": 1, "third": 3,
    }


def test_detail_returns_rating_history_and_underlying_game_links(monkeypatch):
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (_profiles(), _matches()))
    duo_id = canonical_duo_id(ALPHA, BRAVO)

    detail = duo_repository.get_duo_detail(object(), duo_id)

    assert detail is not None
    assert [item.game_id for item in detail.games] == [f"game-{i}" for i in range(1, 6)]
    assert detail.rating_history == detail.games
    assert detail.head_to_head[0].game_ids == [f"game-{i}" for i in range(1, 6)]
    assert detail.head_to_head[0].wins == 3
    assert detail.head_to_head[0].losses == 2


def test_detail_omits_unknown_duo(monkeypatch):
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (_profiles(), _matches()))

    assert duo_repository.get_duo_detail(object(), "missing") is None


class _RpcResponse:
    def __init__(self, data):
        self.data = data


class _SnapshotClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def rpc(self, name, _params=None):
        self.calls.append(name)
        return self

    def execute(self):
        return _RpcResponse(self.snapshot)


def test_source_uses_one_complete_snapshot_rpc_instead_of_uncapped_table_reads():
    client = _SnapshotClient({
        "snapshot_version": "dice-rating-analytics/v1",
        "profiles": _profiles(),
        "games": [{
            "id": "game-1", "ranked": True, "team1_score": 11, "team2_score": 8,
            "winner_team": 1, "played_at": "2026-01-01T00:00:00Z", "created_at": "2026-01-01T00:00:01Z",
            "live_result_state": None,
        }],
        "players": [
            {"game_id": "game-1", "user_id": ALPHA, "team": 1},
            {"game_id": "game-1", "user_id": BRAVO, "team": 1},
            {"game_id": "game-1", "user_id": CHARLIE, "team": 2},
            {"game_id": "game-1", "user_id": DELTA, "team": 2},
        ],
    })

    profiles, matches = duo_repository._source(client)

    assert len(profiles) == 4
    assert matches[0].team1 == (ALPHA, BRAVO)
    assert client.calls == ["dice_duo_replay_snapshot"]


def test_source_fails_closed_when_snapshot_history_limit_is_exceeded():
    client = _SnapshotClient({
        "snapshot_version": "dice-rating-analytics/v1",
        "error": "history_limit_exceeded",
    })
    import pytest

    with pytest.raises(RuntimeError, match="exceeds"):
        duo_repository._source(client)


def test_hidden_member_is_not_exposed_in_ladder_or_detail(monkeypatch):
    profiles = _profiles()
    profiles[0] = {**profiles[0], "hide_from_leaderboard": True}
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (profiles, _matches()))
    duo_id = canonical_duo_id(ALPHA, BRAVO)

    ladder = duo_repository.list_duo_ladder(object())

    assert all(item.duo_id != duo_id for item in ladder.ranked)
    assert duo_repository.get_duo_detail(object(), duo_id) is None


def test_hidden_opponent_games_do_not_change_visible_duo_replay(monkeypatch):
    visible = (ALPHA, BRAVO)
    hidden = (CHARLIE, DELTA)
    matches = [
        DuoMatch(
            game_id="hidden-game",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            team1=visible,
            team2=hidden,
            winner_team=2,
            team1_score=1,
            team2_score=11,
        ),
        DuoMatch(
            game_id="visible-game",
            played_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            team1=visible,
            team2=("u-e", "u-f"),
            winner_team=1,
            team1_score=11,
            team2_score=8,
        ),
    ]
    profiles = _profiles() + [
        {"user_id": user_id, "display_name": user_id, "avatar_url": None}
        for user_id in ("u-e", "u-f")
    ]
    profiles[2] = {**profiles[2], "hide_from_leaderboard": True}
    profiles[3] = {**profiles[3], "hide_from_leaderboard": True}
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (profiles, matches))

    detail = duo_repository.get_duo_detail(object(), canonical_duo_id(*visible))

    assert detail is not None
    assert detail.summary.games == 1
    assert detail.summary.wins == 1
    assert [item.game_id for item in detail.games] == ["visible-game"]


def test_homepage_filter_is_applied_before_the_limit(monkeypatch):
    matches = _matches() + [
        DuoMatch(
            game_id=f"provisional-{index}",
            played_at=datetime(2026, 2, index, tzinfo=timezone.utc),
            team1=(f"p{index}", f"q{index}"),
            team2=(f"r{index}", f"s{index}"),
            winner_team=1,
            team1_score=11,
            team2_score=9,
        )
        for index in range(1, 5)
    ]
    profiles = _profiles() + [
        {"user_id": user_id, "display_name": user_id, "avatar_url": None}
        for index in range(1, 5)
        for user_id in (f"p{index}", f"q{index}", f"r{index}", f"s{index}")
    ]
    monkeypatch.setattr(duo_repository, "_source", lambda _supabase: (profiles, matches))

    ladder = duo_repository.list_duo_ladder(object(), limit=1, homepage_eligible_only=True)

    assert len(ladder.ranked) == 1
    assert ladder.ranked[0].games == 5


def _synergy_matches():
    from dice.duo_synergy import SynergyMatch
    from dataclasses import asdict
    return [SynergyMatch(**asdict(match), elo_before=dict.fromkeys((*match.team1, *match.team2), 1500)) for match in _matches()]


def test_synergy_lists_are_signed_sorted_and_independent_of_ladder_limit(monkeypatch):
    from dataclasses import replace
    matches = _synergy_matches()
    profiles = _profiles()
    for index in range(4):
        left, right = (f"left{index}", f"mate{index}"), (f"right{index}", f"other{index}")
        profiles += [{"user_id": member, "display_name": member} for member in (*left, *right)]
        matches += [replace(match, game_id=f"pair{index}-{i}", team1=left, team2=right,
                            winner_team=1, team1_score=11, team2_score=2,
                            elo_before=dict.fromkeys((*left, *right), 1500)) for i, match in enumerate(_synergy_matches())]
    monkeypatch.setattr(duo_repository, "_source", lambda _: (profiles, matches))
    ladder = duo_repository.list_duo_ladder(object(), limit=1)
    assert len(ladder.ranked) == 1
    assert len(ladder.best_chemistry) == len(ladder.better_apart) == 3
    assert [row.synergy.wins_above_expected for row in ladder.best_chemistry] == [2.5] * 3
    assert [row.synergy.wins_above_expected for row in ladder.better_apart] == [-2.5] * 3
    detail = duo_repository.get_duo_detail(object(), canonical_duo_id(ALPHA, BRAVO))
    assert detail.summary.synergy.wins_above_expected == 0.5
    assert detail.big_moments is None


def test_best_partner_is_positive_only_and_hidden_matches_never_contribute(monkeypatch):
    monkeypatch.setattr(duo_repository, "_source", lambda _: (_profiles(), _synergy_matches()))
    assert duo_repository.get_best_partner(object(), ALPHA).members[1].user_id == BRAVO
    assert duo_repository.get_best_partner(object(), CHARLIE) is None
    profiles = _profiles()
    profiles[2]["hide_from_leaderboard"] = True
    monkeypatch.setattr(duo_repository, "_source", lambda _: (profiles, _synergy_matches()))
    assert duo_repository.get_best_partner(object(), ALPHA) is None
    assert duo_repository.list_duo_ladder(object()).best_chemistry == []


def test_big_moments_does_not_read_live_tables_below_gate():
    assert duo_repository._big_moments(object(), (ALPHA, BRAVO), [], [str(i) for i in range(9)]) is None


def test_live_ledger_adapter_returns_split_only_at_ten_games():
    from dataclasses import replace
    rules = {"contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
             "target_score": 11, "win_by": 2, "call_policy": {
                 "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
                 "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
                 "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"}}
    matches = [replace(_synergy_matches()[0], game_id=f"game-{i}") for i in range(10)]
    live_rows = [{"id": f"live-{i}", "official_result_id": match.game_id, "status": "completed",
                  "team_order": ["blue", "clay"], "teams": {"blue": [ALPHA, BRAVO], "clay": [CHARLIE, DELTA]},
                  "rules_snapshot": rules} for i, match in enumerate(matches)]
    events = {}
    for row in live_rows:
        common = {"match_id": row["id"], "recorded_by": "ref", "recorded_at": "2026-08-24T12:00:00Z", "match_elapsed_ms": 0}
        # A mistaken Alpha point is replaced with Bravo's point. Only Bravo
        # should receive positive swing in the final split.
        events[row["id"]] = [
            {**common, "id": "e1", "match_version": 1, "sequence": 1, "client_command_id": "c1", "command_index": 0,
             "kind": "observation", "thrower_id": ALPHA, "throwing_team_id": "blue", "outcome": "point", "score_delta": [1, 0]},
            {**common, "id": "e2", "match_version": 2, "sequence": 2, "client_command_id": "c2", "command_index": 0,
             "kind": "correction", "target_event_id": "e1", "reason": "mistaken_entry"},
            {**common, "id": "e3", "match_version": 2, "sequence": 3, "client_command_id": "c2", "command_index": 1,
             "kind": "observation", "thrower_id": BRAVO, "throwing_team_id": "blue", "outcome": "point",
             "score_delta": [1, 0], "replacement_for": "e1"},
        ]

    class Query:
        def __init__(self, table):
            self.table = table
            self.match_id = None
        def select(self, *_): return self
        def in_(self, *_): return self
        def eq(self, key, value):
            if key == "match_id": self.match_id = value
            return self
        def is_(self, *_): return self
        def order(self, *_): return self
        def range(self, *_): return self
        def execute(self):
            return _RpcResponse(live_rows if self.table == "dice_live_matches" else [{"event": event} for event in events[self.match_id]])
    class Client:
        def table(self, table): return Query(table)

    live_rows.pop()
    assert duo_repository._big_moments(Client(), (ALPHA, BRAVO), matches, [m.game_id for m in matches]) is None
    live_rows.append({**live_rows[0], "id": "live-9", "official_result_id": "game-9"})
    result = duo_repository._big_moments(Client(), (ALPHA, BRAVO), matches, [m.game_id for m in matches])
    assert result is not None
    assert result["games"] == 10
    assert [row["share"] for row in result["members"]] == [0.0, 1.0]


def test_detail_rank_matches_displayed_elo_ladder(monkeypatch):
    from dataclasses import replace
    profiles = _profiles() + [{"user_id": member, "display_name": member} for member in ("e", "f", "g", "h")]
    matches = [replace(match, game_id=f"long-{batch}-{index}")
               for batch in range(6) for index, match in enumerate(_synergy_matches())]
    matches += [replace(match, game_id=f"short-{index}", team1=("e", "f"), team2=("g", "h"))
                for index, match in enumerate(_synergy_matches()[:3])]
    monkeypatch.setattr(duo_repository, "_source", lambda _: (profiles, matches))
    ladder = duo_repository.list_duo_ladder(object())
    # The new pair has higher displayed Elo but wider uncertainty; ordering by
    # conservative score here would disagree with the ladder.
    assert ladder.ranked[0].duo_id == canonical_duo_id("e", "f")
    assert ladder.ranked[0].conservative_score < ladder.ranked[1].conservative_score
    for duo in ladder.ranked:
        detail = duo_repository.get_duo_detail(object(), duo.duo_id)
        assert detail.summary.rank == duo.rank
