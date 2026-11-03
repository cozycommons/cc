from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dice.duo_rating import canonical_duo_id
from dice.duo_synergy import (
    BIG_MOMENTS_MIN_LIVE_GAMES, DUO_SYNERGY_MIN_GAMES,
    SynergyMatch, calculate_big_moments, calculate_duo_synergies,
)
from dice.elo import expected_score


def game(index, *, team1=("a", "b"), team2=("c", "d"), winner=1, ratings=None, **changes):
    return SynergyMatch(
        game_id=f"game-{index}", played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        team1=team1, team2=team2, winner_team=winner,
        team1_score=11 if winner == 1 else 3, team2_score=3 if winner == 1 else 11,
        elo_before=ratings if ratings is not None else dict.fromkeys((*team1, *team2), 1500),
        **changes,
    )


def test_threshold_and_empty_apart_records():
    pair = canonical_duo_id("a", "b")
    matches = [game(i) for i in range(DUO_SYNERGY_MIN_GAMES)]
    assert calculate_duo_synergies(matches[:-1]) == {}
    result = calculate_duo_synergies(matches)[pair]
    assert result == {"wins": 5, "losses": 0, "games": 5, "expected_wins": 2.5,
                      "wins_above_expected": 2.5, "apart": []}


def test_expected_wins_use_each_game_stored_individual_team_average():
    ratings = {"a": 1400, "b": 1800, "c": 1500, "d": 1900}
    matches = [game(i, ratings=ratings) for i in range(4)] + [game(4, winner=2)]
    result = calculate_duo_synergies(matches)
    expected = 4 * expected_score(1600, 1700) + 0.5
    assert result[canonical_duo_id("a", "b")]["expected_wins"] == pytest.approx(expected)
    assert result[canonical_duo_id("a", "b")]["wins_above_expected"] == pytest.approx(4 - expected)
    assert sum(row["expected_wins"] for row in result.values()) == pytest.approx(5)


def test_losing_pair_with_both_members_winning_apart_and_reversed_teams():
    matches = [game(i, winner=2) for i in range(5)]
    matches += [game(5, team1=("a", "e"), team2=("f", "g")),
                game(6, team1=("f", "g"), team2=("e", "b"), winner=2)]
    result = calculate_duo_synergies(matches)[canonical_duo_id("b", "a")]
    assert result["wins_above_expected"] == -2.5
    assert result["apart"] == [{"user_id": member, "wins": 1, "losses": 0, "games": 1} for member in ("a", "b")]


def test_apart_records_exclude_same_pair_on_opposite_team():
    matches = [game(i) for i in range(5)] + [game(5, team1=("c", "d"), team2=("b", "a"))]
    result = calculate_duo_synergies(matches)[canonical_duo_id("a", "b")]
    assert result["games"] == 6
    assert result["apart"] == []


@pytest.mark.parametrize("changes", [
    {"ranked": False}, {"completed": False}, {"live_result_state": "reopened"},
    {"live_result_state": "completed"}, {"team1": ("a",)}, {"team2": ("a", "d")},
    {"team1_score": 1, "team2_score": 11}, {"winner_team": None},
])
def test_ineligible_games_do_not_count_together_or_apart(changes):
    matches = [game(i) for i in range(4)]
    matches += [replace(game(5), **changes)]
    assert calculate_duo_synergies(matches) == {}


@pytest.mark.parametrize("bad_rating", [None, float("nan"), float("inf"), True])
def test_missing_or_invalid_snapshots_never_use_a_fallback_rating(bad_rating):
    matches = [game(i) for i in range(4)] + [game(4, ratings={"a": bad_rating, "b": 1500, "c": 1500, "d": 1500})]
    assert calculate_duo_synergies(matches) == {}


def test_big_moments_gate_uses_only_distinct_live_ranked_games_together():
    matches = [game(i) for i in range(BIG_MOMENTS_MIN_LIVE_GAMES)]
    points = {match.game_id: [{"thrower_id": "a", "swing": 0.3}, {"thrower_id": "b", "swing": 0.1}] for match in matches}
    assert calculate_big_moments(("a", "b"), matches[:-1], points) is None
    assert calculate_big_moments(("a", "b"), matches, {key: value for key, value in points.items() if key != "game-9"}) is None
    result = calculate_big_moments(("b", "a"), matches, points)
    assert result["games"] == 10
    assert [row["share"] for row in result["members"]] == pytest.approx([0.75, 0.25])
    assert calculate_big_moments(("a", "c"), matches, points) is None
    assert calculate_big_moments(("a", "b"), [replace(m, ranked=False) for m in matches], points) is None
    assert calculate_big_moments(("a", "b"), [replace(m, live_result_state="reopened") for m in matches], points) is None


def test_big_moments_normalize_team_two_and_ignore_negative_or_unattributed_swing():
    matches = [game(i, team1=("c", "d"), team2=("b", "a")) for i in range(10)]
    points = {match.game_id: [
        {"thrower_id": "a", "swing": -0.3}, {"thrower_id": "b", "swing": -0.1},
        {"thrower_id": "a", "swing": 0.5}, {"thrower_id": "c", "swing": -0.8},
        {"thrower_id": None, "swing": -0.5},
    ] for match in matches}
    result = calculate_big_moments(("a", "b"), matches, points)
    assert [row["share"] for row in result["members"]] == pytest.approx([0.75, 0.25])
    assert calculate_big_moments(("a", "b"), matches, {match.game_id: [] for match in matches}) is None
