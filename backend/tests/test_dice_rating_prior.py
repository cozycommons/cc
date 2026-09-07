import pytest

from dice.live_types import DiceLiveError, DiceLiveErrorCode
from dice.rating_prior import RatingSnapshot, team_average_prior


def _rating(user_id, rating, version="1.0.0"):
    return RatingSnapshot(user_id=user_id, rating=rating, system_version=version)


def test_team_average_prior_is_symmetric_for_equal_ratings():
    left = (_rating("a", 1600), _rating("b", 1400))
    right = (_rating("c", 1500), _rating("d", 1500))
    assert team_average_prior(left, right) == pytest.approx(0.5)


def test_team_average_prior_moves_with_server_rating_snapshot():
    assert team_average_prior((_rating("a", 1800),), (_rating("b", 1500),)) > 0.8


def test_team_average_prior_rejects_missing_or_mixed_snapshots():
    with pytest.raises(DiceLiveError) as missing:
        team_average_prior((), (_rating("b", 1500),))
    assert missing.value.code == DiceLiveErrorCode.INVALID_ROSTER
    with pytest.raises(DiceLiveError) as mixed:
        team_average_prior((_rating("a", 1500),), (_rating("b", 1500, "2.0.0"),))
    assert mixed.value.code == DiceLiveErrorCode.INVALID_STATE
