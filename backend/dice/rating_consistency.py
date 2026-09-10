"""Validation for read-only snapshots of the canonical Dice rating state."""

from __future__ import annotations

from dice.rating_replay import build_rating_plan


PROFILE_STATE_FIELDS = (
    "user_id", "elo_rating", "rating_deviation", "elo_model_version",
    "ranked_games_played", "games_played", "wins", "losses",
    "ranked_wins", "ranked_losses", "normal_wins", "normal_losses",
    "self_sinks", "sinks",
)
PLAYER_STATE_FIELDS = (
    "id", "elo_before", "elo_after",
    "rating_deviation_before", "rating_deviation_after",
)
GAME_SOURCE_FIELDS = (
    "id", "ranked", "winner_team", "team1_score", "team2_score",
    "played_at", "created_at", "live_result_state",
)
PLAYER_SOURCE_FIELDS = ("id", "game_id", "user_id", "team", "self_sinks", "sinks")


def _project(row: dict, fields: tuple[str, ...], label: str) -> dict:
    if not isinstance(row, dict) or any(field not in row for field in fields):
        raise ValueError(f"{label} rows are incomplete")
    return {field: row[field] for field in fields}


def validate_canonical_rating_snapshot(
    profiles: list[dict], games: list[dict], players: list[dict]
) -> None:
    """Fail unless official history reproduces every persisted rating field."""

    # The analytics snapshot is shared with duo replay and therefore contains
    # duo-only games. Canonical individual state intentionally excludes that
    # history, so remove the rows at this validation boundary as well as in the
    # profile-progress reader and SQL mutation source.
    duo_only_game_ids = {
        row["id"]
        for row in games
        if isinstance(row, dict) and row.get("duo_only", False) and "id" in row
    }
    games = [
        row for row in games
        if not isinstance(row, dict) or row.get("id") not in duo_only_game_ids
    ]
    players = [
        row for row in players
        if not isinstance(row, dict) or row.get("game_id") not in duo_only_game_ids
    ]
    source = {
        "profiles": [{"user_id": _project(row, PROFILE_STATE_FIELDS, "profile")["user_id"]}
                     for row in profiles],
        "games": [_project(row, GAME_SOURCE_FIELDS, "game") for row in games],
        "players": [_project(row, PLAYER_SOURCE_FIELDS, "game-player") for row in players],
    }
    players_by_game: dict[str, list[dict]] = {}
    for player in source["players"]:
        players_by_game.setdefault(player["game_id"], []).append(player)
    for game in source["games"]:
        if game["ranked"] and game["winner_team"] in (1, 2):
            roster = players_by_game.get(game["id"], [])
            team1 = sum(player["team"] == 1 for player in roster)
            team2 = sum(player["team"] == 2 for player in roster)
            if not team1 or team1 != team2:
                raise ValueError(f"completed ranked game {game['id']} has an incomplete roster")
    plan = build_rating_plan(source)
    actual_profiles = sorted(
        (_project(row, PROFILE_STATE_FIELDS, "profile") for row in profiles),
        key=lambda row: row["user_id"],
    )
    actual_players = sorted(
        (_project(row, PLAYER_STATE_FIELDS, "game-player") for row in players),
        key=lambda row: row["id"],
    )
    if actual_profiles != plan.profile_states or actual_players != plan.player_snapshots:
        raise ValueError("canonical replay does not match stored state")
