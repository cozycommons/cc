from datetime import datetime, timedelta, timezone

import pytest

from dice.duo_rating import (
    DUO_HOMEPAGE_GAMES,
    DUO_PLACEMENT_GAMES,
    DuoMatch,
    DuoRatingState,
    build_duo_ladder,
    canonical_duo_id,
    canonical_duo_members,
    conservative_duo_score,
    eligible_duo_matches,
    rank_duos,
    replay_duo_history,
    replay_duo_history_with_transitions,
)
from dice.rating_deviation import INITIAL_RATING_DEVIATION


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def game(
    game_id: str,
    day: int,
    team1: tuple[str, str] = ("alice", "bob"),
    team2: tuple[str, str] = ("carol", "dave"),
    *,
    winner: int | None = 1,
    ranked: bool = True,
    completed: bool = True,
    live_result_state: str | None = "official",
    score: tuple[int, int] | None = None,
) -> DuoMatch:
    score = score or ((21, 10) if winner == 1 else (10, 21))
    return DuoMatch(
        game_id=game_id,
        played_at=START + timedelta(days=day),
        team1=team1,
        team2=team2,
        winner_team=winner,
        team1_score=score[0],
        team2_score=score[1],
        ranked=ranked,
        completed=completed,
        live_result_state=live_result_state,
    )


def test_canonical_pair_is_sorted_unordered_and_distinct():
    assert canonical_duo_members("z", "a") == ("a", "z")
    assert canonical_duo_id("z", "a") == canonical_duo_id("a", "z")
    assert canonical_duo_id("a", "bc") != canonical_duo_id("ab", "c")
    with pytest.raises(ValueError, match="distinct"):
        canonical_duo_members("same", "same")


def test_only_completed_ranked_valid_2v2_games_are_eligible():
    candidates = [
        game("valid", 0),
        game("normal", 1, ranked=False),
        game("incomplete", 2, completed=False),
        game("live", 3, live_result_state="active"),
        game("no-winner", 4, winner=None),
        game("one-v-one", 5, team1=("alice", "bob"), team2=("carol",)),
        game("three", 6, team1=("alice", "bob"), team2=("carol", "dave"), winner=2),
        game("duplicate", 7, team1=("alice", "alice")),
    ]
    assert [match.game_id for match, *_ in eligible_duo_matches(candidates)] == [
        "valid",
        "three",
    ]
    states = replay_duo_history(candidates)
    assert sum(state.ranked_games for state in states.values()) == 4


@pytest.mark.parametrize(
    "bad_score",
    [(10, 21), (21, 21), (-1, 10)],
)
def test_score_inconsistent_or_malformed_results_are_excluded(bad_score):
    assert eligible_duo_matches([game("bad", 0, score=bad_score)]) == []


def test_non_numeric_mapping_scores_are_excluded_without_coercion():
    raw = {
        "id": "bad-mapping",
        "played_at": "2026-01-01T00:00:00Z",
        "team1": ["alice", "bob"],
        "team2": ["carol", "dave"],
        "winner_team": 1,
        "team1_score": "eleven",
        "team2_score": 8,
    }
    assert eligible_duo_matches([raw]) == []


def test_duplicate_game_ids_are_rejected_before_replay():
    with pytest.raises(ValueError, match="game IDs must be unique"):
        eligible_duo_matches([game("same", 0), game("same", 1)])


def test_mapping_and_dataclass_inputs_have_the_same_defaults_and_timestamp_handling():
    typed = game("g1", 0)
    mapping = {
        "id": "g1",
        "played_at": "2026-01-01T00:00:00Z",
        "team1": ["alice", "bob"],
        "team2": ["carol", "dave"],
        "winner_team": 1,
        "team1_score": 21,
        "team2_score": 10,
    }
    assert replay_duo_history([typed]) == replay_duo_history([mapping])


def test_seeded_duo_ids_retain_members_when_they_first_appear():
    duo_id = canonical_duo_id("alice", "bob")
    states = replay_duo_history([game("g1", 0)], [duo_id])
    assert states[duo_id].members == ("alice", "bob")


def test_replay_order_is_independent_of_input_and_uses_game_id_tiebreaker():
    same_time = [
        game("z-loss", 0, winner=2),
        game("a-win", 0, winner=1),
        game("later", 1, winner=1),
    ]
    forward_states, forward_transitions = replay_duo_history_with_transitions(same_time)
    shuffled_states, shuffled_transitions = replay_duo_history_with_transitions(
        [same_time[2], same_time[0], same_time[1]]
    )
    assert forward_states == shuffled_states
    assert forward_transitions == shuffled_transitions
    assert [transition.game_id for transition in forward_transitions[::2]] == [
        "a-win",
        "z-loss",
        "later",
    ]


def test_duos_start_at_1500_rd_350_and_change_independently_of_players():
    states, transitions = replay_duo_history_with_transitions([])
    assert states == {}
    states = replay_duo_history([game("g1", 0)])
    alice_bob = states[canonical_duo_id("alice", "bob")]
    carol_dave = states[canonical_duo_id("carol", "dave")]
    assert alice_bob.elo > 1500
    assert carol_dave.elo < 1500
    assert alice_bob.ranked_games == carol_dave.ranked_games == 1
    assert alice_bob.deviation < INITIAL_RATING_DEVIATION
    assert transitions == []


def test_every_game_has_one_transition_per_duo_with_source_evidence():
    states, transitions = replay_duo_history_with_transitions([game("g1", 0)])
    assert len(transitions) == 2
    assert {transition.game_id for transition in transitions} == {"g1"}
    assert {transition.result for transition in transitions} == {"win", "loss"}
    assert {transition.result: transition.score for transition in transitions} == {
        "win": (21, 10),
        "loss": (10, 21),
    }
    for transition in transitions:
        assert transition.after_elo - transition.before_elo == transition.delta
        assert transition.after == states[transition.duo_id]
        assert transition.opponent_duo_id != transition.duo_id


def test_three_games_place_a_duo_and_qualify_for_homepage():
    matches = [game(f"g{index}", index) for index in range(DUO_HOMEPAGE_GAMES)]
    ladder = build_duo_ladder(matches)
    assert len(ladder.ranked) == 2
    assert all(state.ranked_games == DUO_HOMEPAGE_GAMES for state in ladder.ranked)

    two_game_ladder = build_duo_ladder(matches[: DUO_PLACEMENT_GAMES - 1])
    assert two_game_ladder.ranked == ()
    assert len(two_game_ladder.to_watch) == 2
    assert not any(state.homepage_eligible for state in two_game_ladder.to_watch)

    three_game_ladder = build_duo_ladder(matches[:DUO_PLACEMENT_GAMES])
    assert len(three_game_ladder.ranked) == 2
    assert three_game_ladder.to_watch == ()
    assert all(state.homepage_eligible for state in three_game_ladder.ranked)
    assert all(state.homepage_eligible for state in ladder.ranked)


def test_correcting_an_early_result_replays_all_later_duo_ratings():
    original = [game("g1", 0), game("g2", 1), game("g3", 2)]
    corrected = [game("g1", 0, winner=2), *original[1:]]
    original_states = replay_duo_history(original)
    corrected_states = replay_duo_history(corrected)
    duo_id = canonical_duo_id("alice", "bob")
    assert original_states[duo_id].wins == 3
    assert corrected_states[duo_id].wins == 2
    assert corrected_states[duo_id].elo != original_states[duo_id].elo


def test_duo_streaks_follow_ranked_results_and_keep_game_links():
    matches = [
        game("win-1", 0),
        game("win-2", 1),
        game("loss", 2, winner=2),
        game("win-3", 3),
        game("win-4", 4),
        game("win-5", 5),
    ]
    states, transitions = replay_duo_history_with_transitions(matches)
    duo_id = canonical_duo_id("alice", "bob")
    state = states[duo_id]
    assert (state.current_streak, state.best_streak) == (3, 3)
    assert [transition.game_id for transition in transitions if transition.duo_id == duo_id] == [
        "win-1",
        "win-2",
        "loss",
        "win-3",
        "win-4",
        "win-5",
    ]


def test_conservative_score_values_more_evidence_without_driving_rank():
    matches = []
    for index in range(20):
        matches.append(
            game(
                f"long-{index}",
                index,
                team1=("long-a", "long-b"),
                team2=("long-o", "long-p"),
            )
        )
    matches.append(
        game(
            "long-loss",
            20,
            team1=("long-a", "long-b"),
            team2=("long-o", "long-p"),
            winner=2,
        )
    )
    for index in range(8):
        matches.append(
            game(
                f"short-{index}",
                index,
                team1=("short-a", "short-b"),
                team2=("short-o", "short-p"),
            )
        )
    ladder = build_duo_ladder(matches)
    long_run = next(state for state in ladder.ranked if state.members == ("long-a", "long-b"))
    short_run = next(state for state in ladder.ranked if state.members == ("short-a", "short-b"))
    assert (long_run.wins, long_run.losses) == (20, 1)
    assert (short_run.wins, short_run.losses) == (8, 0)
    assert conservative_duo_score(long_run) > conservative_duo_score(short_run)


def test_ladder_ranks_placed_duos_by_the_elo_people_see():
    more_certain = DuoRatingState(
        "certain", ("a", "b"), elo=1520, deviation=50, ranked_games=5,
    )
    less_certain = DuoRatingState(
        "uncertain", ("c", "d"), elo=1579, deviation=200, ranked_games=3,
    )

    ladder = rank_duos([more_certain, less_certain])

    assert [state.duo_id for state in ladder.ranked] == ["uncertain", "certain"]
