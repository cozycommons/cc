"""Typed, persistence-free Elo prior inputs for live prediction."""

from __future__ import annotations

from dataclasses import dataclass

from dice.elo import expected_score
from dice.live_types import DiceLiveError, DiceLiveErrorCode


@dataclass(frozen=True, slots=True)
class RatingSnapshot:
    user_id: str
    rating: int
    system_version: str


def team_average_prior(
    team1: tuple[RatingSnapshot, ...], team2: tuple[RatingSnapshot, ...]
) -> float:
    """Return the Elo matchup prior without reading persistence or client input."""
    if not team1 or not team2:
        raise DiceLiveError(DiceLiveErrorCode.INVALID_ROSTER, "both teams need a rating snapshot")
    versions = {item.system_version for item in (*team1, *team2)}
    if len(versions) != 1:
        raise DiceLiveError(DiceLiveErrorCode.INVALID_STATE, "rating snapshots use mixed system versions")
    left = sum(item.rating for item in team1) / len(team1)
    right = sum(item.rating for item in team2) / len(team2)
    return expected_score(left, right)
