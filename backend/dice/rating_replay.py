"""Deterministic canonical Elo replay and persistence payload planning."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from dice.rating_config import CANONICAL_RATING_VERSION
from dice.rating_deviation import RankedMatch, replay_ranked_history_with_transitions
from supabase import Client


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _datetime(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _sort_source(source: dict) -> None:
    source["profiles"].sort(key=lambda row: row["user_id"])
    source["games"].sort(
        key=lambda row: (_datetime(row["played_at"]), _datetime(row["created_at"]), row["id"])
    )
    source["players"].sort(key=lambda row: (row["game_id"], row["user_id"], row["id"]))


@dataclass(frozen=True)
class RatingPlan:
    source: dict
    player_snapshots: list[dict]
    profile_states: list[dict]
    source_digest: str
    output_digest: str
    eligible_ranked_games: int


def project_game_mutation(
    source: dict,
    operation: str,
    game: dict,
    players: list[dict],
) -> dict:
    """Return the exact raw source expected after one manual game mutation."""

    if operation not in {"create", "update", "delete"}:
        raise ValueError("rating mutation operation must be create, update, or delete")
    projected = deepcopy(source)
    game_id = game["id"]
    existing = any(row["id"] == game_id for row in projected["games"])
    if operation == "create" and existing:
        raise ValueError("game already exists")
    if operation in {"update", "delete"} and not existing:
        raise ValueError("game not found")
    projected["games"] = [row for row in projected["games"] if row["id"] != game_id]
    projected["players"] = [row for row in projected["players"] if row["game_id"] != game_id]
    if operation != "delete":
        projected["games"].append(deepcopy(game))
        projected["players"].extend({**deepcopy(row), "game_id": game_id} for row in players)
    _sort_source(projected)
    return projected


def build_rating_plan(source: dict) -> RatingPlan:
    """Build the complete canonical Elo and aggregate state for one source."""

    if not isinstance(source, dict):
        raise ValueError("rating source snapshot must be an object")
    source = deepcopy(source)
    profiles = source.get("profiles")
    games = source.get("games")
    players = source.get("players")
    if not all(isinstance(rows, list) for rows in (profiles, games, players)):
        raise ValueError("rating source snapshot arrays are required")

    required_game = {
        "id", "ranked", "winner_team", "team1_score", "team2_score",
        "played_at", "created_at", "live_result_state",
    }
    required_player = {"id", "game_id", "user_id", "team", "self_sinks", "sinks"}
    if any(not isinstance(row, dict) for rows in (profiles, games, players) for row in rows):
        raise ValueError("rating source rows must be objects")
    if any("user_id" not in row for row in profiles):
        raise ValueError("rating source profile rows are incomplete")
    if any(not required_game <= row.keys() for row in games):
        raise ValueError("rating source game rows are incomplete")
    if any(not required_player <= row.keys() for row in players):
        raise ValueError("rating source player rows are incomplete")
    identity_values = (
        [row["user_id"] for row in profiles]
        + [row["id"] for row in games]
        + [value for row in players for value in (row["id"], row["game_id"], row["user_id"])]
    )
    if any(not isinstance(value, str) or not value for value in identity_values):
        raise ValueError("rating source identities must be non-empty strings")
    profile_ids = [row["user_id"] for row in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("rating source profiles must be unique")
    game_ids = [row["id"] for row in games]
    player_ids = [row["id"] for row in players]
    if len(game_ids) != len(set(game_ids)):
        raise ValueError("rating source games must be unique")
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("rating source players must be unique")
    profile_id_set = set(profile_ids)
    game_id_set = set(game_ids)
    if any(row["game_id"] not in game_id_set or row["user_id"] not in profile_id_set for row in players):
        raise ValueError("rating source players reference unknown identities")
    participants = [(row["game_id"], row["user_id"]) for row in players]
    if len(participants) != len(set(participants)):
        raise ValueError("rating source game participants must be unique")
    players_by_game: dict[str, list[dict]] = {}
    for row in players:
        players_by_game.setdefault(row["game_id"], []).append(row)

    matches: list[RankedMatch] = []
    eligible_game_ids: set[str] = set()
    ordered_games = sorted(
        games,
        key=lambda row: (_datetime(row["played_at"]), _datetime(row["created_at"]), row["id"]),
    )
    for game in ordered_games:
        if game.get("live_result_state") not in (None, "official"):
            continue
        roster = players_by_game.get(game["id"], [])
        team1 = tuple(row["user_id"] for row in roster if row["team"] == 1)
        team2 = tuple(row["user_id"] for row in roster if row["team"] == 2)
        eligible = bool(
            game["ranked"]
            and game["winner_team"] in (1, 2)
            and team1
            and len(team1) == len(team2)
        )
        if not eligible:
            continue
        eligible_game_ids.add(game["id"])
        matches.append(
            RankedMatch(
                game_id=game["id"],
                played_at=_datetime(game["played_at"]),
                team1=team1,
                team2=team2,
                winner_team=game["winner_team"],
                team1_score=game["team1_score"],
                team2_score=game["team2_score"],
            )
        )

    final_states, transitions = replay_ranked_history_with_transitions(matches, profile_ids)
    transition_by_game = {transition.game_id: transition for transition in transitions}
    player_snapshots = []
    for row in players:
        transition = transition_by_game.get(row["game_id"])
        before = transition.before.get(row["user_id"]) if transition else None
        after = transition.after.get(row["user_id"]) if transition else None
        player_snapshots.append(
            {
                "id": row["id"],
                "elo_before": before.elo if before else None,
                "elo_after": after.elo if after else None,
                "rating_deviation_before": round(before.deviation, 2) if before else None,
                "rating_deviation_after": round(after.deviation, 2) if after else None,
            }
        )

    aggregates = {
        user_id: {
            "games_played": 0, "wins": 0, "losses": 0,
            "ranked_wins": 0, "ranked_losses": 0,
            "normal_wins": 0, "normal_losses": 0,
            "self_sinks": 0, "sinks": 0,
        }
        for user_id in profile_ids
    }
    for game in ordered_games:
        if game.get("live_result_state") not in (None, "official"):
            continue
        for player in players_by_game.get(game["id"], []):
            state = aggregates[player["user_id"]]
            state["games_played"] += 1
            state["self_sinks"] += player["self_sinks"]
            state["sinks"] += player["sinks"]
            if game["winner_team"] not in (1, 2):
                continue
            won = player["team"] == game["winner_team"]
            if game["id"] in eligible_game_ids:
                state["wins" if won else "losses"] += 1
                state["ranked_wins" if won else "ranked_losses"] += 1
            elif not game["ranked"]:
                state["wins" if won else "losses"] += 1
                state["normal_wins" if won else "normal_losses"] += 1

    profile_states = []
    for user_id in profile_ids:
        rating = final_states[user_id]
        profile_states.append(
            {
                "user_id": user_id,
                "elo_rating": rating.elo,
                "rating_deviation": round(rating.deviation, 2),
                "elo_model_version": CANONICAL_RATING_VERSION,
                "ranked_games_played": rating.ranked_games,
                **aggregates[user_id],
            }
        )
    player_snapshots.sort(key=lambda row: row["id"])
    profile_states.sort(key=lambda row: row["user_id"])
    output = {"players": player_snapshots, "profiles": profile_states}
    return RatingPlan(
        source=source,
        player_snapshots=player_snapshots,
        profile_states=profile_states,
        source_digest=_digest(source),
        output_digest=_digest(output),
        eligible_ranked_games=len(eligible_game_ids),
    )


def verify_rating_state(actual: dict, plan: RatingPlan) -> None:
    """Require the persisted canonical generation to equal the plan exactly."""

    if (
        not isinstance(actual, dict)
        or not isinstance(actual.get("players"), list)
        or not isinstance(actual.get("profiles"), list)
    ):
        raise RuntimeError("dice_rating.state_snapshot_unavailable")
    normalized = {
        "players": sorted(actual["players"], key=lambda row: row["id"]),
        "profiles": sorted(actual["profiles"], key=lambda row: row["user_id"]),
    }
    expected = {"players": plan.player_snapshots, "profiles": plan.profile_states}
    if normalized != expected:
        raise RuntimeError("dice_rating.post_commit_mismatch")
    if _digest(normalized) != plan.output_digest:
        raise RuntimeError("dice_rating.post_commit_digest_mismatch")


def _clear_client_cache(client: Client) -> None:
    clear_cache = getattr(client, "clear_cache", None)
    if callable(clear_cache):
        clear_cache()


def apply_game_rating_mutation(
    client: Client,
    operation: str,
    game: dict,
    players: list[dict],
    attempts: int = 3,
    mutation_id: str | None = None,
    actor_id: str | None = None,
    request_fingerprint: str | None = None,
) -> dict:
    """Apply a raw game mutation and its canonical generation atomically."""

    mutation_id = str(uuid.UUID(mutation_id)) if mutation_id else str(uuid.uuid4())
    for attempt in range(attempts):
        source = client.rpc("dice_rating_source_snapshot").execute().data
        applied_game = game
        if operation == "update":
            current_game = next(
                (row for row in source.get("games", []) if row.get("id") == game.get("id")),
                None,
            )
            if current_game is None:
                raise ValueError("game not found")
            applied_game = {**current_game, **game}
        expected_source = project_game_mutation(source, operation, applied_game, players)
        plan = build_rating_plan(expected_source)
        try:
            result = client.rpc(
                "dice_rating_apply_game_mutation",
                {
                    "p_mutation_id": mutation_id,
                    "p_source": source,
                    "p_operation": operation,
                    "p_game": applied_game,
                    "p_players": players,
                    "p_expected_source": plan.source,
                    "p_player_snapshots": plan.player_snapshots,
                    "p_profile_states": plan.profile_states,
                    "p_source_digest": plan.source_digest,
                    "p_output_digest": plan.output_digest,
                    "p_actor_id": actor_id,
                    "p_request_fingerprint": request_fingerprint,
                },
            ).execute().data
        except Exception as mutation_error:  # noqa: BLE001 - transports use several exception types
            if "dice_rating.idempotency_conflict" in str(mutation_error):
                raise ValueError("idempotency key conflicts with an earlier request") from mutation_error
            try:
                receipt = client.rpc(
                    "dice_rating_mutation_receipt", {"p_mutation_id": mutation_id}
                ).execute().data
                expected_receipt = {
                    "mutation_id": mutation_id,
                    "operation": operation,
                    "game_id": applied_game["id"],
                    "source_digest": plan.source_digest,
                    "output_digest": plan.output_digest,
                    "players_updated": len(plan.player_snapshots),
                    "profiles_updated": len(plan.profile_states),
                    "actor_id": actor_id,
                    "request_fingerprint": request_fingerprint,
                }
                replay_matches_request = (
                    operation == "create"
                    and isinstance(receipt, dict)
                    and receipt.get("mutation_id") == mutation_id
                    and receipt.get("operation") == operation
                    and receipt.get("game_id") == applied_game["id"]
                    and receipt.get("actor_id") == actor_id
                    and receipt.get("request_fingerprint") == request_fingerprint
                )
                if receipt != expected_receipt and not replay_matches_request:
                    raise RuntimeError("dice_rating.mutation_receipt_mismatch")
            except Exception:  # noqa: BLE001 - preserve the original RPC failure
                if "dice_rating.source_changed" in str(mutation_error) and attempt + 1 < attempts:
                    continue
                raise mutation_error
            _clear_client_cache(client)
            return {
                "operation": operation,
                "game_id": applied_game["id"],
                "game": applied_game,
                "plan": plan,
                "reconciled_after_transport_error": True,
                "replayed": replay_matches_request,
            }
        expected_counts = {
            "players_updated": len(plan.player_snapshots),
            "profiles_updated": len(plan.profile_states),
        }
        expected_receipt_fields = {
            "mutation_id": mutation_id,
            "operation": operation,
            "game_id": applied_game["id"],
            "source_digest": plan.source_digest,
            "output_digest": plan.output_digest,
            "actor_id": actor_id,
            "request_fingerprint": request_fingerprint,
            **expected_counts,
        }
        replay_matches_request = (
            operation == "create"
            and isinstance(result, dict)
            and result.get("replayed") is True
            and result.get("mutation_id") == mutation_id
            and result.get("operation") == operation
            and result.get("game_id") == applied_game["id"]
            and result.get("actor_id") == actor_id
            and result.get("request_fingerprint") == request_fingerprint
        )
        if not replay_matches_request and (
            not isinstance(result, dict)
            or {key: result.get(key) for key in expected_receipt_fields} != expected_receipt_fields
        ):
            raise RuntimeError("dice_rating.mutation_result_mismatch")
        if not replay_matches_request and result.get("replayed") is not True:
            verify_rating_state(result.get("state"), plan)
        _clear_client_cache(client)
        return {
            "operation": operation,
            "game_id": applied_game["id"],
            "game": applied_game,
            "plan": plan,
            "replayed": replay_matches_request,
            **expected_counts,
        }
    raise AssertionError("unreachable")
