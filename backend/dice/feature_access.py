"""Compatibility responses for the retired Dice live-referee rollout flag."""

from __future__ import annotations

from enum import Enum

class DiceFeature(str, Enum):
    LIVE_REFEREE = "dice_live_referee"


def feature_state(feature: DiceFeature) -> dict[str, bool]:
    """Keep cached pre-retirement clients on the released experience."""
    return {"opted_in": True, "effective": True}


def feature_states() -> dict[str, dict[str, bool]]:
    return {
        feature.value: feature_state(feature)
        for feature in DiceFeature
    }
