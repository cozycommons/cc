"""Small, versioned, independently evaluated Dice probability baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, log
from statistics import mean

from dice.prediction_dataset import DATASET_VERSION, PredictionRow

MODEL_ID = "dice-pregame-logistic"
MODEL_VERSION = "1.0.0"
FEATURE_NAMES = ("prior_win_rate_difference",)


@dataclass(frozen=True, slots=True)
class PredictionModel:
    model_id: str
    model_version: str
    dataset_version: str
    coefficients: tuple[float, ...]
    training_games: int

    def as_dict(self) -> dict:
        return asdict(self)


# Accepted on the 2026-08-29 2v2 production evaluation (35 train, 15 holdout;
# Brier 0.2383 versus neutral 0.2500), then refit on all 50 eligible games.
ACCEPTED_MODEL = PredictionModel(
    MODEL_ID, MODEL_VERSION, DATASET_VERSION, (1.93085824,), 50
)

# Retain every served artifact here so a deployment never changes the prior
# for an in-flight match created by an older model version.
SUPPORTED_MODELS = {
    (ACCEPTED_MODEL.model_id, ACCEPTED_MODEL.model_version, ACCEPTED_MODEL.dataset_version): ACCEPTED_MODEL,
}


def _features(row: PredictionRow) -> tuple[float, ...]:
    return (row.prior_win_rate_difference,)


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = exp(-value)
        return 1 / (1 + inverse)
    positive = exp(value)
    return positive / (1 + positive)


def fit_prediction_model(rows: list[PredictionRow], *, iterations: int = 3000,
                         learning_rate: float = 0.15, l2: float = 0.001) -> PredictionModel:
    if len(rows) < 10:
        raise ValueError("at least 10 completed games are required to fit a prediction model")
    if {row.dataset_version for row in rows} != {DATASET_VERSION}:
        raise ValueError("prediction training rows must use the supported dataset version")
    coefficients = [0.0] * len(FEATURE_NAMES)
    for _ in range(iterations):
        gradient = [0.0] * len(coefficients)
        for row in rows:
            features = _features(row)
            probability = _sigmoid(sum(weight * feature for weight, feature in zip(coefficients, features)))
            error = probability - row.team1_won
            for index, feature in enumerate(features):
                gradient[index] += error * feature
        for index in range(len(coefficients)):
            regularization = l2 * coefficients[index]
            coefficients[index] -= learning_rate * (gradient[index] / len(rows) + regularization)
    return PredictionModel(MODEL_ID, MODEL_VERSION, rows[0].dataset_version,
                           tuple(round(value, 8) for value in coefficients), len(rows))


def predict(model: PredictionModel, row: PredictionRow) -> float:
    if row.dataset_version != model.dataset_version:
        raise ValueError("prediction row and model dataset versions differ")
    return _sigmoid(sum(weight * feature for weight, feature in zip(model.coefficients, _features(row))))


def predict_features(model: PredictionModel, prior_win_rate_difference: float) -> float:
    features = (prior_win_rate_difference,)
    if len(model.coefficients) != len(features):
        raise ValueError("prediction model feature contract differs")
    return _sigmoid(sum(weight * feature for weight, feature in zip(model.coefficients, features)))


def _metrics(probabilities: list[float], outcomes: list[int]) -> dict:
    clipped = [max(1e-9, min(1 - 1e-9, value)) for value in probabilities]
    return {"brier": round(mean((value - outcome) ** 2 for value, outcome in zip(clipped, outcomes)), 4),
            "log_loss": round(mean(-(outcome * log(value) + (1 - outcome) * log(1 - value))
                                   for value, outcome in zip(clipped, outcomes)), 4)}


def evaluate_prediction_baselines(rows: list[PredictionRow], *, train_fraction: float = 0.7) -> dict:
    split = max(10, min(len(rows) - 5, round(len(rows) * train_fraction)))
    if len(rows) < 15 or split <= 0:
        raise ValueError("at least 15 chronological games are required for held-out evaluation")
    train, test = rows[:split], rows[split:]
    model = fit_prediction_model(train)
    outcomes = [row.team1_won for row in test]
    probabilities = [predict(model, row) for row in test]
    buckets = []
    for lower in (0.0, 0.25, 0.5, 0.75):
        members = [(probability, outcome) for probability, outcome in zip(probabilities, outcomes)
                   if lower <= probability < lower + 0.25 or lower == 0.75 and probability == 1]
        if members:
            buckets.append({"range": [lower, lower + 0.25], "games": len(members),
                            "mean_prediction": round(mean(item[0] for item in members), 3),
                            "observed_rate": round(mean(item[1] for item in members), 3)})
    return {"model": model.as_dict(), "split": {"train_games": len(train), "test_games": len(test)},
            "metrics": {"independent_model": _metrics(probabilities, outcomes),
                        "neutral_50": _metrics([0.5] * len(test), outcomes),
                        "elo_expected_score": _metrics([row.elo_probability for row in test], outcomes)},
            "calibration": buckets}
