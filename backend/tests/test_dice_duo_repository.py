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
