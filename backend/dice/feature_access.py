"""Private Dice capability gates.

Feature access is only a rollout boundary. It must not influence scoring,
projectors, stored event interpretation, or a game's rules version.
"""

from __future__ import annotations

from enum import Enum

from supabase import Client

FEATURE_ACCESS_TABLE = "dice_feature_access"


class DiceFeature(str, Enum):
    LIVE_REFEREE = "dice_live_referee"


def _known_feature(feature: DiceFeature | str) -> DiceFeature | None:
    try:
        return DiceFeature(feature)
    except ValueError:
        return None


def has_profile_access(supabase: Client, user_id: str, feature: DiceFeature | str) -> bool:
    """Return stored access, failing closed for missing or unknown features."""
    known = _known_feature(feature)
    if known is None:
        return False
    rows = (
        supabase.table(FEATURE_ACCESS_TABLE)
        .select("enabled")
        .eq("user_id", user_id)
        .eq("feature", known.value)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows and rows[0].get("enabled") is True)


def is_feature_enabled(
    supabase: Client,
    user_id: str,
    feature: DiceFeature | str,
) -> bool:
    """Return the profile-level access gate for a known Dice capability."""
    return has_profile_access(supabase, user_id, feature)


def feature_state(supabase: Client, user_id: str, feature: DiceFeature) -> dict[str, bool]:
    opted_in = has_profile_access(supabase, user_id, feature)
    return {
        "opted_in": opted_in,
        "effective": opted_in,
    }


def feature_states(supabase: Client, user_id: str) -> dict[str, dict[str, bool]]:
    return {
        feature.value: feature_state(supabase, user_id, feature)
        for feature in DiceFeature
    }


def set_profile_access(
    supabase: Client, user_id: str, feature: DiceFeature, enabled: bool
) -> None:
    supabase.table(FEATURE_ACCESS_TABLE).upsert(
        {"user_id": user_id, "feature": feature.value, "enabled": enabled},
        on_conflict="user_id,feature",
    ).execute()
