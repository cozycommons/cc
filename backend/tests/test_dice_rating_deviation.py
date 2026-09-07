from datetime import datetime, timedelta, timezone

import pytest

from dice.elo import expected_score
from dice.rating_deviation import (
    ESTABLISHED_K,
    INITIAL_RATING_DEVIATION,
    MAX_RATING_DEVIATION,
    MIN_RATING_DEVIATION,
    PROVISIONAL_K,
    RankedMatch,
    after_ranked_game,
    bounded_team_delta,
    effective_k_factor,
    inflate_for_inactivity,
    probability,
    replay_ranked_history,
    team_deviation,
)


def test_probability_mapping_is_the_existing_elo_function():
    assert probability(1500, 1500) == expected_score(1500, 1500) == pytest.approx(0.5)
    assert probability(1800, 1500) == expected_score(1800, 1500)


def test_placement_starts_at_legacy_k_and_tapers_with_confidence():
    initial = effective_k_factor(PROVISIONAL_K, INITIAL_RATING_DEVIATION)
    after_one_result = effective_k_factor(
        PROVISIONAL_K, after_ranked_game(INITIAL_RATING_DEVIATION)
    )

    assert initial == PROVISIONAL_K
    assert after_one_result < initial
    assert effective_k_factor(PROVISIONAL_K, MIN_RATING_DEVIATION) == PROVISIONAL_K // 2


def test_established_players_still_adjust_learning_rate_with_deviation():
    assert effective_k_factor(ESTABLISHED_K, INITIAL_RATING_DEVIATION) > ESTABLISHED_K
    assert effective_k_factor(ESTABLISHED_K, MIN_RATING_DEVIATION) < ESTABLISHED_K


def test_one_result_cannot_move_more_than_one_effective_k():
    assert bounded_team_delta(1300, 1700, True, 40, 2.0) == 40
    assert bounded_team_delta(1700, 1300, False, 40, 2.0) == -40
    assert bounded_team_delta(1700, 1300, False, 20, 2.0) == -20


def test_ordinary_result_keeps_the_existing_elo_delta():
    assert bounded_team_delta(1500, 1500, True, 20) == 10
    assert bounded_team_delta(1500, 1500, False, 20) == -10


def test_inactivity_increases_deviation_but_never_changes_skill():
    before = MIN_RATING_DEVIATION
    assert inflate_for_inactivity(before, 0) == before
    assert inflate_for_inactivity(before, 30) > before
    assert inflate_for_inactivity(INITIAL_RATING_DEVIATION, 365) == MAX_RATING_DEVIATION


def test_ranked_result_reduces_uncertainty_after_inactivity_is_applied():
    assert after_ranked_game(INITIAL_RATING_DEVIATION) < INITIAL_RATING_DEVIATION
    assert after_ranked_game(MIN_RATING_DEVIATION, 30) > MIN_RATING_DEVIATION
    assert after_ranked_game(MIN_RATING_DEVIATION, 30) < inflate_for_inactivity(MIN_RATING_DEVIATION, 30)


def test_team_deviation_is_symmetric_and_rejects_empty_teams():
    assert team_deviation((50, 50)) == pytest.approx(50)
    assert team_deviation((50, 350)) == team_deviation((350, 50))
    with pytest.raises(ValueError, match="at least one"):
        team_deviation(())


def test_replay_is_deterministic_and_inactivity_only_changes_deviation():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    matches = [
        RankedMatch(start, ("a",), ("b",), 1, 11, 5),
        RankedMatch(start + timedelta(days=45), ("a",), ("b",), 2, 11, 9),
    ]
    first = replay_ranked_history(matches, ("a", "b"))
    second = replay_ranked_history(matches, ("a", "b"))

    assert first == second
    assert first["a"].ranked_games == 2
    assert first["a"].last_ranked_at == matches[-1].played_at
    assert first["a"].deviation < INITIAL_RATING_DEVIATION
    assert first["b"].deviation < INITIAL_RATING_DEVIATION
    assert first["a"].elo != 1500 or first["b"].elo != 1500


def test_replay_preserves_elo_probability_semantics_for_each_matchup():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    states = replay_ranked_history(
        [RankedMatch(start, ("a",), ("b",), 1, 11, 0)],
        ("a", "b"),
    )
    assert probability(states["a"].elo, states["b"].elo) == expected_score(
        states["a"].elo, states["b"].elo
    )


def test_replay_rejects_unknown_players_and_invalid_winners():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="initial state"):
        replay_ranked_history([RankedMatch(start, ("a",), ("b",), 1, 1, 0)], ("a",))
    with pytest.raises(ValueError, match="winner_team"):
        replay_ranked_history([RankedMatch(start, ("a",), ("b",), 3, 1, 0)], ("a", "b"))


def test_replay_rejects_duplicate_players_and_skips_unbalanced_teams():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="distinct"):
        replay_ranked_history(
            [RankedMatch(start, ("a",), ("a",), 1, 1, 0)],
            ("a",),
        )

    states = replay_ranked_history(
        [RankedMatch(start, ("a", "b"), ("c",), 1, 1, 0)],
        ("a", "b", "c"),
    )
    assert all(state.ranked_games == 0 for state in states.values())
    assert all(state.elo == 1500 for state in states.values())
