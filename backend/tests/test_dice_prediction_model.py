from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from dice.prediction_dataset import build_prediction_dataset
from dice.prediction_model import evaluate_prediction_baselines, fit_prediction_model, predict, predict_features
from dice.rating_deviation import RankedMatch
from scripts.dice_prediction_report import promotion_status


def _rows(count=20):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    matches = [RankedMatch(start + timedelta(days=index), ("a", "c"), ("b", "d"),
                           1 if index % 3 else 2, 11 if index % 3 else 7,
                           7 if index % 3 else 11, f"g{index}") for index in range(count)]
    return build_prediction_dataset(matches)


def test_model_is_deterministic_versioned_and_bounded():
    model = fit_prediction_model(_rows())
    assert model == fit_prediction_model(_rows())
    assert model.model_id == "dice-pregame-logistic"
    assert 0 < predict(model, _rows()[-1]) < 1
    assert 0 < predict_features(model, 0.1) < 1


def test_evaluation_is_time_split_and_compares_baselines():
    report = evaluate_prediction_baselines(_rows())
    assert report["split"] == {"train_games": 14, "test_games": 6}
    assert set(report["metrics"]) == {"independent_model", "neutral_50", "elo_expected_score"}


def test_small_samples_and_mixed_dataset_versions_fail_closed():
    with pytest.raises(ValueError, match="at least 10"):
        fit_prediction_model(_rows(9))
    model = fit_prediction_model(_rows())
    row = replace(_rows()[-1], dataset_version="future")
    with pytest.raises(ValueError, match="versions differ"):
        predict(model, row)
    with pytest.raises(ValueError, match="supported dataset version"):
        fit_prediction_model([*_rows()[:-1], row])


def test_promotion_requires_ten_holdout_games_on_every_split():
    def reports(test_sizes):
        return {
            str(index): {"split": {"test_games": size},
                         "metrics": {"independent_model": {"brier": 0.2},
                                     "neutral_50": {"brier": 0.25}}}
            for index, size in enumerate(test_sizes)
        }

    assert promotion_status(40, reports([20, 16, 12, 8])) == "insufficient_data"
    assert promotion_status(48, reports([24, 19, 14, 10])) == "accepted"
