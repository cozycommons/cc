"""Shared immutable pregame probability for live pulse and duo moments."""

from datetime import datetime, timezone
from math import isclose

from dice.live_types import DiceLiveError
from dice.prediction_model import SUPPORTED_MODELS, predict_features
from dice.rating_prior import RatingSnapshot, team_average_prior


def pregame_probability(row: dict) -> tuple[float, str, str, str, datetime | None]:
    """Read an immutable creation snapshot, preferring the independent model."""

    fallback = (0.5, "neutral_fallback", "neutral", "1.0.0", None)
    snapshot = row.get("prediction_snapshot") or {}
    try:
        captured_at = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        model = SUPPORTED_MODELS.get((snapshot["model_id"], snapshot["model_version"], snapshot["dataset_version"]))
        if model is None:
            return fallback
        prior1 = float(snapshot["team1_prior_win_rate"])
        prior2 = float(snapshot["team2_prior_win_rate"])
        probability = float(snapshot["team1_probability"])
        expected_probability = predict_features(model, prior1 - prior2)
        if (not 0 <= prior1 <= 1 or not 0 <= prior2 <= 1 or not 0 <= probability <= 1
                or not isclose(probability, expected_probability, rel_tol=0, abs_tol=1e-12)
                or abs((captured_at - created_at).total_seconds()) > 300):
            return fallback
        if captured_at > datetime.now(timezone.utc):
            return fallback
        return (probability, "independent_model_snapshot", snapshot["model_id"],
                snapshot["model_version"], captured_at)
    except (KeyError, TypeError, ValueError):
        if snapshot:
            return fallback
    # Matches created before migration 0054 keep their already-immutable Elo
    # snapshot for the life of that match. New matches never take this path.
    try:
        legacy = row["rating_snapshot"]
        teams = {team_id: tuple(RatingSnapshot(**item) for item in legacy[team_id])
                 for team_id in row["team_order"]}
        probability = team_average_prior(teams[row["team_order"][0]], teams[row["team_order"][1]])
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        return probability, "legacy_elo_snapshot", "elo-team-average", "1.0.0", created_at
    except (KeyError, TypeError, ValueError, DiceLiveError):
        return fallback

