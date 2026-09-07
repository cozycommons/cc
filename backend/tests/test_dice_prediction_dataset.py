from datetime import datetime, timedelta, timezone

import pytest

from dice.prediction_dataset import DATASET_VERSION, build_prediction_dataset, ranked_matches_from_rows
from dice.rating_deviation import RankedMatch


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _matches():
    return [
        RankedMatch(START, ("a", "c"), ("b", "d"), 1, 11, 5, "g1"),
        RankedMatch(START + timedelta(days=10), ("a", "c"), ("b", "d"), 2, 8, 11, "g2"),
    ]


def test_dataset_features_are_point_in_time_and_versioned():
    first, second = build_prediction_dataset(_matches())
    assert first.dataset_version == DATASET_VERSION
    assert first.team1_prior_games == first.team2_prior_games == 0
    assert first.team1_prior_win_rate == first.team2_prior_win_rate == 0.5
    assert first.elo_probability == 0.5
    assert second.team1_prior_games == second.team2_prior_games == 1
    assert second.team1_prior_win_rate > second.team2_prior_win_rate
    assert second.team1_days_since_last == second.team2_days_since_last == 10


def test_appending_a_future_game_cannot_change_prior_feature_rows():
    original = build_prediction_dataset(_matches())
    future = RankedMatch(START + timedelta(days=20), ("a", "c"), ("b", "d"), 1, 11, 0, "g3")
    extended = build_prediction_dataset([*_matches(), future])
    assert extended[:2] == original


def test_dataset_rejects_duplicate_games_and_players():
    with pytest.raises(ValueError, match="game IDs must be unique"):
        build_prediction_dataset([_matches()[0], _matches()[0]])
    duplicate = RankedMatch(START, ("a", "a"), ("b", "d"), 1, 11, 5, "bad")
    with pytest.raises(ValueError, match="distinct"):
        build_prediction_dataset([duplicate])


def test_row_adapter_fails_closed_on_a_partially_written_official_game():
    game = {"id": "g1", "ranked": True, "winner_team": 1, "team1_score": 11,
            "team2_score": 5, "played_at": START.isoformat(), "created_at": START.isoformat(),
            "live_result_state": None}
    with pytest.raises(ValueError, match="2v2 roster"):
        ranked_matches_from_rows([game], [{"id": "p1", "game_id": "g1", "user_id": "a", "team": 1}])
    with pytest.raises(ValueError, match="no roster"):
        ranked_matches_from_rows([game], [])


def test_dataset_rejects_balanced_singles_because_live_serving_is_2v2():
    with pytest.raises(ValueError, match="2v2"):
        build_prediction_dataset([RankedMatch(START, ("a",), ("b",), 1, 11, 5, "singles")])
