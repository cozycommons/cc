"""Supabase-backed persistence for the Dice team score/ELO tracker."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from dice.elo import (
    PROVISIONAL_GAMES_THRESHOLD,
    STARTING_ELO,
)
from dice.rating_deviation import INITIAL_RATING_DEVIATION
from dice.rating_config import CANONICAL_RATING_VERSION
from dice.rating_replay import RatingPlan, apply_game_rating_mutation
from dice.schemas import (
    CreateGameRequest,
    CreateScheduledMatchRequest,
    CreateTournamentRequest,
    DiceGame,
    DiceProfile,
    DiceTournament,
    GameComment,
    HeadToHeadRecord,
    LeaderboardEntry,
    RatingProgress,
    RatingProgressPoint,
    SelfSinkEntry,
    SetBracketTeamsRequest,
    SinkEntry,
    UpdateGameRequest,
    UpdateScheduledMatchRequest,
    UpdateTournamentRequest,
)
from supabase import Client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreatedGame:
    game: DiceGame
    replayed: bool

BRACKET_SLOTS = ("semi1", "semi2", "final")
MAX_FINALISTS = 8  # 4 bracket corners, up to 2 players each (2v2); a 1v1 bracket only uses 4

PROFILES_TABLE = "dice_profiles"
GAMES_TABLE = "dice_games"
GAME_PLAYERS_TABLE = "dice_game_players"
GAME_COMMENTS_TABLE = "dice_game_comments"
TOURNAMENTS_TABLE = "dice_tournaments"
TOURNAMENT_ENROLLMENTS_TABLE = "dice_tournament_enrollments"

PROFILE_COLUMNS = (
    "user_id, display_name, avatar_url, elo_rating, rating_deviation, elo_model_version, games_played, "
    "ranked_games_played, wins, losses, ranked_wins, ranked_losses, "
    "normal_wins, normal_losses, self_sinks, sinks, hide_from_leaderboard, "
    "phone_number, sms_notifications_enabled"
)

GAME_COLUMNS = "id, created_by, ranked, duo_only, team1_score, team2_score, winner_team, played_at, created_at, updated_at, tournament_id, source_live_match_id, recorded_stats"
LIVE_RESULT_COLUMNS = "id, source_live_match_id, team1_score, team2_score, winner_team, live_result_state, termination_reason, detail_coverage, stats_complete"
LIVE_RATING_PLAYER_COLUMNS = "id, game_id, user_id, team, counts_for_group_stage, self_sinks, sinks"


def _official_games(query):
    # PostgREST's `is` operator only accepts null/true/false/unknown, so
    # `not.is.reopened` is rejected outright (every caller 400s). Match the
    # RLS policy's "is null or = official" shape with an explicit or-filter.
    return query.or_("live_result_state.is.null,live_result_state.eq.official")


def get_live_result(supabase: Client, source_live_match_id: str) -> dict | None:
    """Read the one mutable official-result materialization for a live match."""
    rows = (supabase.table(GAMES_TABLE).select(LIVE_RESULT_COLUMNS)
            .eq("source_live_match_id", source_live_match_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def sync_live_result_rating(
    supabase: Client,
    match_id: str,
    ranked: bool | None = None,
    *,
    bounded: bool = False,
) -> None:
    """Rebuild canonical ratings after a live projection changes ranking state."""
    result = get_live_result(supabase, match_id)
    if not result:
        return
    game = {"id": result["id"]}
    if ranked is not None:
        game["ranked"] = ranked
    players = (supabase.table(GAME_PLAYERS_TABLE).select(LIVE_RATING_PLAYER_COLUMNS)
               .eq("game_id", result["id"]).execute().data or [])
    apply_game_rating_mutation(
        supabase,
        "update",
        game,
        players,
        rpc_name=(
            "dice_live_apply_ranked_rating_mutation"
            if bounded
            else "dice_rating_apply_game_mutation"
        ),
    )


def has_pending_live_rating_repair(supabase: Client, match_id: str) -> bool:
    rows = (
        supabase.table("dice_live_rating_repairs")
        .select("match_id")
        .eq("match_id", match_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows)


def list_pending_live_rating_repairs(supabase: Client, limit: int = 25) -> list[str]:
    rows = (
        supabase.table("dice_live_rating_repairs")
        .select("match_id")
        .order("updated_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    return [str(row["match_id"]) for row in rows]


def record_live_rating_repair_failure(supabase: Client, match_id: str, error: Exception) -> None:
    rows = (
        supabase.table("dice_live_rating_repairs")
        .select("attempts")
        .eq("match_id", match_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return
    supabase.table("dice_live_rating_repairs").update({
        "attempts": int(rows[0].get("attempts") or 0) + 1,
        "last_error": str(error)[:1000],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("match_id", match_id).execute()


def get_game_source_live_match_id(supabase: Client, game_id: str) -> str | None:
    rows = (supabase.table(GAMES_TABLE).select("source_live_match_id")
            .eq("id", game_id).limit(1).execute().data or [])
    return rows[0].get("source_live_match_id") if rows else None


def _profile_from_row(row: dict) -> DiceProfile:
    return DiceProfile.model_validate(row)


def get_profile(supabase: Client, user_id: str) -> Optional[DiceProfile]:
    rows = (
        supabase.table(PROFILES_TABLE)
        .select(PROFILE_COLUMNS)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return _profile_from_row(rows[0]) if rows else None


def get_or_create_profile(
    supabase: Client,
    user_id: str,
    default_display_name: str,
    default_avatar_url: Optional[str],
) -> DiceProfile:
    existing = get_profile(supabase, user_id)
    if existing:
        return existing
    row = {
        "user_id": user_id,
        "display_name": default_display_name,
        "avatar_url": default_avatar_url,
        "elo_rating": STARTING_ELO,
        "ranked_games_played": 0,
        "rating_deviation": INITIAL_RATING_DEVIATION,
        "elo_model_version": CANONICAL_RATING_VERSION,
    }
    response = supabase.table(PROFILES_TABLE).insert(row).execute()
    return _profile_from_row(response.data[0])


def update_profile(
    supabase: Client,
    user_id: str,
    display_name: Optional[str],
    avatar_url: Optional[str],
    hide_from_leaderboard: Optional[bool] = None,
    phone_number: Optional[str] = None,
    sms_notifications_enabled: Optional[bool] = None,
) -> DiceProfile:
    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if display_name is not None:
        updates["display_name"] = display_name
    if avatar_url is not None:
        updates["avatar_url"] = avatar_url
    if hide_from_leaderboard is not None:
        updates["hide_from_leaderboard"] = hide_from_leaderboard
    if phone_number is not None:
        updates["phone_number"] = phone_number
    if sms_notifications_enabled is not None:
        if sms_notifications_enabled:
            effective_phone = phone_number
            if effective_phone is None:
                existing = get_profile(supabase, user_id)
                effective_phone = existing.phone_number if existing else None
            if not effective_phone:
                raise ValueError("add a phone number before enabling game notifications")
        updates["sms_notifications_enabled"] = sms_notifications_enabled
    response = (
        supabase.table(PROFILES_TABLE).update(updates).eq("user_id", user_id).execute()
    )
    if not response.data:
        raise ValueError("Profile not found")
    return _profile_from_row(response.data[0])


def search_profiles(supabase: Client, query: str, limit: int) -> list[DiceProfile]:
    q = supabase.table(PROFILES_TABLE).select(PROFILE_COLUMNS)
    if query:
        q = q.ilike("display_name", f"%{query}%")
    rows = q.order("display_name").limit(limit).execute().data or []
    return [_profile_from_row(row) for row in rows]


def list_elo_leaderboard(
    supabase: Client, limit: int, include_provisional: bool = False
) -> list[LeaderboardEntry]:
    """Established players ranked by ELO, optionally with provisional
    (still-in-placements) players appended after them.

    Provisional players' ELO hasn't stabilized, so they're never mixed into
    the ranked ordering itself — the home page preview only ever wants the
    established ranking, while the full leaderboard page also lists
    provisional players (flagged via `is_provisional`) below it.
    """
    established_rows = (
        supabase.table(PROFILES_TABLE)
        .select(PROFILE_COLUMNS)
        .eq("hide_from_leaderboard", False)
        .gte("ranked_games_played", PROVISIONAL_GAMES_THRESHOLD)
        .order("elo_rating", desc=True)
        .order("display_name")
        .order("user_id")
        .limit(limit + 1)
        .execute()
        .data
        or []
    )
    ranked_rows = _with_competition_ranks(established_rows)[:limit]
    if not include_provisional:
        return [LeaderboardEntry.model_validate(row) for row in ranked_rows]

    provisional_rows = (
        supabase.table(PROFILES_TABLE)
        .select(PROFILE_COLUMNS)
        .eq("hide_from_leaderboard", False)
        .lt("ranked_games_played", PROVISIONAL_GAMES_THRESHOLD)
        .order("elo_rating", desc=True)
        .order("display_name")
        .order("user_id")
        .limit(limit)
        .execute()
        .data
        or []
    )
    combined = (ranked_rows + provisional_rows)[:limit]
    return [LeaderboardEntry.model_validate(row) for row in combined]


def _with_competition_ranks(rows: list[dict]) -> list[dict]:
    """Assign 1, 2, 2, 4 competition ranks with explicit tie metadata."""

    counts: dict[int, int] = {}
    for row in rows:
        rating = row["elo_rating"]
        counts[rating] = counts.get(rating, 0) + 1
    ranked: list[dict] = []
    rank = 0
    prior_rating: int | None = None
    for position, row in enumerate(rows, start=1):
        rating = row["elo_rating"]
        if rating != prior_rating:
            rank = position
            prior_rating = rating
        ranked.append({**row, "rank": rank, "is_tied": counts[rating] > 1})
    return ranked


def list_self_sink_leaderboard(
    supabase: Client, limit: int, nonzero_only: bool
) -> list[SelfSinkEntry]:
    q = supabase.table(PROFILES_TABLE).select(PROFILE_COLUMNS).eq("hide_from_leaderboard", False)
    if nonzero_only:
        q = q.gt("self_sinks", 0)
    rows = q.order("self_sinks", desc=True).limit(limit).execute().data or []
    return [SelfSinkEntry.model_validate(row) for row in rows]


def list_sink_leaderboard(supabase: Client, limit: int, nonzero_only: bool) -> list[SinkEntry]:
    q = supabase.table(PROFILES_TABLE).select(PROFILE_COLUMNS).eq("hide_from_leaderboard", False)
    if nonzero_only:
        q = q.gt("sinks", 0)
    rows = q.order("sinks", desc=True).limit(limit).execute().data or []
    return [SinkEntry.model_validate(row) for row in rows]


def _players_for_games(supabase: Client, game_ids: list[str]) -> dict[str, list[dict]]:
    if not game_ids:
        return {}
    player_rows = (
        supabase.table(GAME_PLAYERS_TABLE)
        .select("game_id, user_id, team, counts_for_group_stage, self_sinks, sinks, elo_before, elo_after, rating_deviation_before, rating_deviation_after")
        .in_("game_id", game_ids)
        .execute()
        .data
        or []
    )
    user_ids = list({row["user_id"] for row in player_rows})
    profiles_by_id: dict[str, dict] = {}
    if user_ids:
        profile_rows = (
            supabase.table(PROFILES_TABLE)
            .select("user_id, display_name, avatar_url")
            .in_("user_id", user_ids)
            .execute()
            .data
            or []
        )
        profiles_by_id = {row["user_id"]: row for row in profile_rows}

    grouped: dict[str, list[dict]] = {gid: [] for gid in game_ids}
    for row in player_rows:
        profile = profiles_by_id.get(row["user_id"], {})
        grouped.setdefault(row["game_id"], []).append(
            {
                "user_id": row["user_id"],
                "display_name": profile.get("display_name", "Unknown"),
                "avatar_url": profile.get("avatar_url"),
                "team": row["team"],
                "counts_for_group_stage": row.get("counts_for_group_stage", True),
                "self_sinks": row["self_sinks"],
                "sinks": row["sinks"],
                "elo_before": row["elo_before"],
                "elo_after": row["elo_after"],
                "rating_deviation_before": row.get("rating_deviation_before"),
                "rating_deviation_after": row.get("rating_deviation_after"),
            }
        )
    return grouped


def _game_from_row(row: dict, players: list[dict]) -> DiceGame:
    return DiceGame.model_validate({**row, "players": players})


def _committed_game(
    game: dict,
    players: list[dict],
    profiles_by_id: dict[str, dict],
    plan: RatingPlan,
) -> DiceGame:
    snapshots = {row["id"]: row for row in plan.player_snapshots}
    hydrated_players = []
    for player in players:
        profile = profiles_by_id[player["user_id"]]
        hydrated_players.append({
            **player,
            **snapshots[player["id"]],
            "display_name": profile["display_name"],
            "avatar_url": profile.get("avatar_url"),
        })
    return _game_from_row(game, hydrated_players)


def list_games(supabase: Client, limit: int, offset: int = 0) -> list[DiceGame]:
    rows = (
        _official_games(supabase.table(GAMES_TABLE).select(GAME_COLUMNS))
        .eq("duo_only", False)
        .order("played_at", desc=True)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
        .data
        or []
    )
    players_by_game = _players_for_games(supabase, [row["id"] for row in rows])
    return [_game_from_row(row, players_by_game.get(row["id"], [])) for row in rows]


def list_games_for_user(supabase: Client, user_id: str, limit: int) -> list[DiceGame]:
    player_rows = (
        supabase.table(GAME_PLAYERS_TABLE)
        .select("game_id")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    game_ids = [row["game_id"] for row in player_rows]
    if not game_ids:
        return []
    rows = (
        _official_games(supabase.table(GAMES_TABLE).select(GAME_COLUMNS))
        .eq("duo_only", False)
        .in_("id", game_ids)
        .order("played_at", desc=True)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    players_by_game = _players_for_games(supabase, [row["id"] for row in rows])
    return [_game_from_row(row, players_by_game.get(row["id"], [])) for row in rows]


def get_rating_progress(supabase: Client, user_id: str) -> RatingProgress | None:
    """Derive progress from one coherent, audited official-history snapshot."""

    snapshot = supabase.rpc("dice_rating_analytics_snapshot").execute().data or {}
    if snapshot.get("snapshot_version") != "dice-rating-analytics/v1":
        raise ValueError("unsupported rating analytics snapshot")
    profile_rows = snapshot.get("profiles") or []
    profile = next((row for row in profile_rows if row["user_id"] == user_id), None)
    if profile is None:
        return None
    visible = {row["user_id"] for row in profile_rows if not row["hide_from_leaderboard"]}
    players_by_game: dict[str, list[dict]] = {}
    for player in snapshot.get("players") or []:
        players_by_game.setdefault(player["game_id"], []).append(player)
    games = sorted(
        (row for row in snapshot.get("games") or [] if not row.get("duo_only", False)),
        key=lambda row: (
        datetime.fromisoformat(row["played_at"].replace("Z", "+00:00")),
        datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")), row["id"],
        ),
    )
    ratings = {row["user_id"]: STARTING_ELO for row in profile_rows}
    ranked_games = {row["user_id"]: 0 for row in profile_rows}
    personal_best = STARTING_ELO
    history: list[RatingProgressPoint] = []

    def rank_for(target: str) -> tuple[int | None, bool, int]:
        established = [(uid, rating) for uid, rating in ratings.items()
                       if uid in visible and ranked_games.get(uid, 0) >= PROVISIONAL_GAMES_THRESHOLD]
        established.sort(key=lambda item: (-item[1], item[0]))
        if target not in {uid for uid, _ in established}:
            return None, False, len(established)
        target_rating = ratings[target]
        rank = 1 + sum(rating > target_rating for _, rating in established)
        tied = sum(rating == target_rating for _, rating in established) > 1
        return rank, tied, len(established)

    for game in games:
        if not game["ranked"] or game["winner_team"] is None:
            continue
        game_players = players_by_game.get(game["id"], [])
        ranked_players = [player for player in game_players
                          if player.get("elo_before") is not None and player.get("elo_after") is not None]
        if ranked_players and len(ranked_players) != len(game_players):
            raise RuntimeError("rating analytics snapshot contains a partial game transition")
        if len({player["user_id"] for player in ranked_players}) != len(ranked_players):
            raise RuntimeError("rating analytics snapshot contains duplicate game identities")
        for player in ranked_players:
            if (player["user_id"] not in ratings
                    or player["elo_before"] != ratings[player["user_id"]]):
                raise RuntimeError("rating analytics snapshot contains a discontinuous replay")
        target_player = next((player for player in ranked_players if player["user_id"] == user_id), None)
        before_rank, _, _ = rank_for(user_id)
        for player in ranked_players:
            ratings[player["user_id"]] = player["elo_after"]
            ranked_games[player["user_id"]] = ranked_games.get(player["user_id"], 0) + 1
        after_rank, _, _ = rank_for(user_id)
        if target_player is None:
            continue
        reached_personal_best = target_player["elo_after"] > personal_best
        personal_best = max(personal_best, target_player["elo_after"])
        history.append(RatingProgressPoint(
            game_id=game["id"], played_at=game["played_at"],
            rating_before=target_player["elo_before"], rating_after=target_player["elo_after"],
            delta=target_player["elo_after"] - target_player["elo_before"],
            rank_before=before_rank, rank_after=after_rank,
            rank_change=(before_rank - after_rank) if before_rank and after_rank else None,
            is_personal_best=reached_personal_best,
        ))
    current_rank, current_tied, field_size = rank_for(user_id)
    last = history[-1] if history else None
    if any(
        ratings.get(row["user_id"], STARTING_ELO) != row["elo_rating"]
        or ranked_games.get(row["user_id"], 0) != row["ranked_games_played"]
        for row in profile_rows
    ):
        raise RuntimeError("rating analytics snapshot was captured during a stats recompute")
    return RatingProgress(
        rating_system_version=CANONICAL_RATING_VERSION,
        rank_scope="current_visible_established_field",
        current_rating=profile["elo_rating"],
        current_rank=current_rank, current_rank_tied=current_tied, field_size=field_size,
        is_provisional=profile["ranked_games_played"] < PROVISIONAL_GAMES_THRESHOLD,
        placement_games_remaining=max(0, PROVISIONAL_GAMES_THRESHOLD - profile["ranked_games_played"]),
        personal_best=max(personal_best, profile["elo_rating"]),
        last_delta=last.delta if last else None,
        last_rank_change=last.rank_change if last else None,
        history=history,
    )


def get_head_to_head(supabase: Client, viewer_id: str, other_user_id: str) -> HeadToHeadRecord:
    viewer_rows = (
        supabase.table(GAME_PLAYERS_TABLE)
        .select("game_id, team")
        .eq("user_id", viewer_id)
        .execute()
        .data
        or []
    )
    viewer_team_by_game = {row["game_id"]: row["team"] for row in viewer_rows}
    if not viewer_team_by_game:
        return HeadToHeadRecord()

    other_rows = (
        supabase.table(GAME_PLAYERS_TABLE)
        .select("game_id, team")
        .eq("user_id", other_user_id)
        .in_("game_id", list(viewer_team_by_game.keys()))
        .execute()
        .data
        or []
    )
    other_team_by_game = {row["game_id"]: row["team"] for row in other_rows}
    shared_game_ids = list(other_team_by_game.keys())
    if not shared_game_ids:
        return HeadToHeadRecord()

    game_rows = (
        _official_games(supabase.table(GAMES_TABLE).select("id, winner_team, duo_only"))
        .eq("duo_only", False)
        .in_("id", shared_game_ids)
        .execute()
        .data
        or []
    )
    winner_by_game = {row["id"]: row["winner_team"] for row in game_rows}

    record = HeadToHeadRecord()
    for game_id in shared_game_ids:
        viewer_team = viewer_team_by_game[game_id]
        other_team = other_team_by_game[game_id]
        winner_team = winner_by_game.get(game_id)
        if winner_team is None:
            continue
        viewer_won = viewer_team == winner_team
        if viewer_team == other_team:
            record.teammate_wins += 1 if viewer_won else 0
            record.teammate_losses += 0 if viewer_won else 1
        else:
            record.opponent_wins += 1 if viewer_won else 0
            record.opponent_losses += 0 if viewer_won else 1
    return record


def get_game(
    supabase: Client, game_id: str, include_duo_only: bool = False
) -> Optional[DiceGame]:
    query = _official_games(supabase.table(GAMES_TABLE).select(GAME_COLUMNS)).eq("id", game_id)
    if not include_duo_only:
        query = query.eq("duo_only", False)
    rows = (
        query
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    players_by_game = _players_for_games(supabase, [game_id])
    return _game_from_row(rows[0], players_by_game.get(game_id, []))


def _winner_team(team1_score: int, team2_score: int) -> int:
    if team1_score == team2_score:
        raise ValueError("a game must have a winner; scores cannot tie")
    return 1 if team1_score > team2_score else 2


def _validate_tournament_id(supabase: Client, tournament_id: str) -> None:
    existing = supabase.table(TOURNAMENTS_TABLE).select("id").eq("id", tournament_id).limit(1).execute().data or []
    if not existing:
        raise ValueError("tournament not found")


def list_games_for_tournament(supabase: Client, tournament_id: str, limit: int = 200) -> list[DiceGame]:
    rows = (
        _official_games(supabase.table(GAMES_TABLE).select(GAME_COLUMNS))
        .eq("tournament_id", tournament_id)
        .eq("duo_only", False)
        .order("played_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    players_by_game = _players_for_games(supabase, [row["id"] for row in rows])
    return [_game_from_row(row, players_by_game.get(row["id"], [])) for row in rows]


def create_game(
    supabase: Client,
    created_by: str,
    payload: CreateGameRequest,
    mutation_id: str | None = None,
) -> CreatedGame:
    mutation_id = str(uuid.UUID(mutation_id)) if mutation_id else str(uuid.uuid4())
    request_fingerprint = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    prior_receipt = supabase.rpc(
        "dice_rating_mutation_receipt", {"p_mutation_id": mutation_id}
    ).execute().data
    if prior_receipt is not None:
        if (
            prior_receipt.get("operation") != "create"
            or prior_receipt.get("game_id") != mutation_id
            or prior_receipt.get("actor_id") != created_by
            or prior_receipt.get("request_fingerprint") != request_fingerprint
        ):
            raise ValueError("idempotency key conflicts with an earlier request")
        prior_game = get_game(supabase, mutation_id)
        if prior_game is None:
            raise RuntimeError("dice_rating.idempotent_game_unavailable")
        return CreatedGame(prior_game, replayed=True)

    all_user_ids = [p.user_id for p in payload.players]
    existing = (
        supabase.table(PROFILES_TABLE)
        .select("user_id, display_name, avatar_url")
        .in_("user_id", all_user_ids)
        .execute()
        .data
        or []
    )
    if len(existing) != len(all_user_ids):
        raise ValueError("all players must have an existing Dice profile")
    profiles_by_id = {row["user_id"]: row for row in existing}

    if payload.tournament_id:
        _validate_tournament_id(supabase, payload.tournament_id)

    winner_team = _winner_team(payload.team1_score, payload.team2_score)
    now = datetime.now(timezone.utc).isoformat()
    game_id = mutation_id
    game_row = {
        "id": game_id,
        "created_by": created_by,
        "ranked": payload.ranked,
        "team1_score": payload.team1_score,
        "team2_score": payload.team2_score,
        "winner_team": winner_team,
        "played_at": (payload.played_at or datetime.now(timezone.utc)).isoformat(),
        "created_at": now,
        "tournament_id": payload.tournament_id,
        "source_live_match_id": None,
        "live_result_state": None,
        "termination_reason": None,
        "detail_coverage": "complete",
        "stats_complete": True,
    }
    player_rows = [
        {
            "id": str(uuid.uuid5(uuid.UUID(mutation_id), f"{index}:{p.user_id}:{p.team}")),
            "user_id": p.user_id,
            "team": p.team,
            "counts_for_group_stage": p.counts_for_group_stage,
            "self_sinks": p.self_sinks,
            "sinks": p.sinks,
        }
        for index, p in enumerate(payload.players)
    ]
    result = apply_game_rating_mutation(
        supabase,
        "create",
        game_row,
        player_rows,
        mutation_id=mutation_id,
        actor_id=created_by,
        request_fingerprint=request_fingerprint,
    )
    if result.get("replayed"):
        prior_game = get_game(supabase, mutation_id)
        if prior_game is None:
            raise RuntimeError("dice_rating.idempotent_game_unavailable")
        return CreatedGame(prior_game, replayed=True)
    return CreatedGame(
        _committed_game(
            {**result["game"], "updated_at": result["game"]["created_at"]},
            player_rows,
            profiles_by_id,
            result["plan"],
        ),
        replayed=False,
    )


def _reject_live_result_mutation(supabase: Client, game_id: str) -> None:
    rows = (
        supabase.table(GAMES_TABLE)
        .select("source_live_match_id")
        .eq("id", game_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows and rows[0].get("source_live_match_id") is not None:
        raise ValueError("live game results must be changed through the live match")


def update_game(supabase: Client, game_id: str, payload: UpdateGameRequest) -> DiceGame:
    _reject_live_result_mutation(supabase, game_id)
    all_user_ids = [p.user_id for p in payload.players]
    existing = (
        supabase.table(PROFILES_TABLE)
        .select("user_id, display_name, avatar_url")
        .in_("user_id", all_user_ids)
        .execute()
        .data
        or []
    )
    if len(existing) != len(all_user_ids):
        raise ValueError("all players must have an existing Dice profile")
    profiles_by_id = {row["user_id"]: row for row in existing}

    if payload.tournament_id:
        _validate_tournament_id(supabase, payload.tournament_id)

    winner_team = _winner_team(payload.team1_score, payload.team2_score)
    game_updates = {
        "id": game_id,
        "ranked": payload.ranked,
        "team1_score": payload.team1_score,
        "team2_score": payload.team2_score,
        "winner_team": winner_team,
        "tournament_id": payload.tournament_id,
    }
    if payload.played_at:
        game_updates["played_at"] = payload.played_at.isoformat()
    player_rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": p.user_id,
            "team": p.team,
            "counts_for_group_stage": p.counts_for_group_stage,
            "self_sinks": p.self_sinks,
            "sinks": p.sinks,
        }
        for p in payload.players
    ]
    try:
        apply_game_rating_mutation(
            supabase,
            "update",
            game_updates,
            player_rows,
            rpc_name="dice_rating_apply_game_mutation_if_current",
            rpc_parameters={"p_expected_updated_at": payload.expected_updated_at.isoformat()},
        )
    except Exception as exc:  # noqa: BLE001 - PostgREST exposes database errors by message
        if "dice_game.stale_update" in str(exc):
            raise ValueError("dice_game.stale_update") from exc
        raise
    committed = get_game(supabase, game_id)
    if committed is None:
        raise RuntimeError("updated game is unavailable")
    return committed


def delete_game(
    supabase: Client,
    game_id: str,
    deleted_by: str | None = None,
    mutation_id: str | None = None,
) -> None:
    _reject_live_result_mutation(supabase, game_id)
    apply_game_rating_mutation(
        supabase,
        "delete",
        {"id": game_id},
        [],
        mutation_id=mutation_id,
        actor_id=deleted_by,
        request_fingerprint=(
            _game_delete_fingerprint(game_id, deleted_by) if deleted_by else None
        ),
    )


def _game_delete_fingerprint(game_id: str, deleted_by: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {"operation": "delete_game", "game_id": game_id, "deleted_by": deleted_by},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def game_delete_was_committed(
    supabase: Client, mutation_id: str, game_id: str, deleted_by: str
) -> bool:
    mutation_id = str(uuid.UUID(mutation_id))
    receipt = supabase.rpc(
        "dice_rating_mutation_receipt", {"p_mutation_id": mutation_id}
    ).execute().data
    if not isinstance(receipt, dict):
        return False
    expected = {
        "operation": "delete",
        "game_id": game_id,
        "actor_id": deleted_by,
        "request_fingerprint": _game_delete_fingerprint(game_id, deleted_by),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("idempotency key conflicts with an earlier request")
    return True


def delete_live_match(
    supabase: Client,
    match_id: str,
    game_id: str,
    deleted_by: str,
    mutation_id: str | None = None,
) -> None:
    """Tombstone a live match and remove only its derived game projection."""
    try:
        apply_game_rating_mutation(
            supabase,
            "delete",
            {"id": game_id},
            [],
            mutation_id=mutation_id,
            actor_id=deleted_by,
            request_fingerprint=_game_delete_fingerprint(game_id, deleted_by),
            rpc_name="dice_live_delete_with_rating_mutation",
            rpc_parameters={"p_match_id": match_id, "p_deleted_by": deleted_by},
        )
    except Exception as error:
        if "dice_live.delete_source_changed" in str(error):
            raise ValueError("Live match not found") from error
        raise


COMMENT_COLUMNS = "id, game_id, user_id, body, image_url, created_at"


def _comment_from_row(row: dict, profile: dict) -> GameComment:
    return GameComment(
        id=row["id"],
        game_id=row["game_id"],
        user_id=row["user_id"],
        display_name=profile.get("display_name", "Unknown"),
        avatar_url=profile.get("avatar_url"),
        body=row.get("body"),
        image_url=row.get("image_url"),
        created_at=row["created_at"],
    )


def list_comments(supabase: Client, game_id: str) -> list[GameComment]:
    rows = (
        supabase.table(GAME_COMMENTS_TABLE)
        .select(COMMENT_COLUMNS)
        .eq("game_id", game_id)
        .order("created_at")
        .execute()
        .data
        or []
    )
    user_ids = list({row["user_id"] for row in rows})
    profiles_by_id: dict[str, dict] = {}
    if user_ids:
        profile_rows = (
            supabase.table(PROFILES_TABLE)
            .select("user_id, display_name, avatar_url")
            .in_("user_id", user_ids)
            .execute()
            .data
            or []
        )
        profiles_by_id = {row["user_id"]: row for row in profile_rows}
    return [_comment_from_row(row, profiles_by_id.get(row["user_id"], {})) for row in rows]


def list_photos(supabase: Client, limit: int = 100) -> list[GameComment]:
    rows = (
        supabase.table(GAME_COMMENTS_TABLE)
        .select(COMMENT_COLUMNS)
        .not_.is_("image_url", "null")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    user_ids = list({row["user_id"] for row in rows})
    profiles_by_id: dict[str, dict] = {}
    if user_ids:
        profile_rows = (
            supabase.table(PROFILES_TABLE)
            .select("user_id, display_name, avatar_url")
            .in_("user_id", user_ids)
            .execute()
            .data
            or []
        )
        profiles_by_id = {row["user_id"]: row for row in profile_rows}
    return [_comment_from_row(row, profiles_by_id.get(row["user_id"], {})) for row in rows]


def get_comment(supabase: Client, comment_id: str) -> Optional[dict]:
    rows = (
        supabase.table(GAME_COMMENTS_TABLE)
        .select(COMMENT_COLUMNS)
        .eq("id", comment_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def create_comment(
    supabase: Client, game_id: str, user_id: str, body: Optional[str], image_url: Optional[str]
) -> GameComment:
    row = {"game_id": game_id, "user_id": user_id, "body": body, "image_url": image_url}
    response = supabase.table(GAME_COMMENTS_TABLE).insert(row).execute()
    comment_row = response.data[0]
    profile = get_profile(supabase, user_id)
    profile_dict = profile.model_dump() if profile else {}
    return _comment_from_row(comment_row, profile_dict)


def delete_comment(supabase: Client, comment_id: str) -> None:
    supabase.table(GAME_COMMENTS_TABLE).delete().eq("id", comment_id).execute()


def _tournament_players(supabase: Client, user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    rows = (
        supabase.table(PROFILES_TABLE)
        .select("user_id, display_name, avatar_url")
        .in_("user_id", user_ids)
        .execute()
        .data
        or []
    )
    return {row["user_id"]: row for row in rows}


def _match_player(user_id: Optional[str], profiles_by_id: dict[str, dict]) -> dict:
    if user_id is None:
        return {"user_id": None, "display_name": "TBD", "avatar_url": None}
    return profiles_by_id.get(user_id, {"user_id": user_id, "display_name": "Unknown"})


def _match_user_ids(data: dict) -> set[str]:
    return (
        {
            uid
            for m in (data.get("scheduled_matches") or [])
            for uid in (m.get("team1_player_ids") or []) + (m.get("team2_player_ids") or [])
            if uid
        }
        | {uid for uid in (data.get("finalists") or []) if uid}
        | {uid for team in (data.get("bracket_teams") or []) for uid in team if uid}
    )


def _bracket_team_size(data: dict) -> int:
    """1 (1v1) or 2 (2v2) — inferred from whichever bracket team was set,
    since set_bracket_teams enforces the same size across all four corners.
    Defaults to 2 before the host has assembled any teams."""
    for team in data.get("bracket_teams") or []:
        if team:
            return len(team)
    return 2


def _bracket_teams(data: dict) -> list[list[Optional[str]]]:
    # 4 explicit bracket corners, each a team (1 or 2 players, consistent
    # across the bracket) the host assembled from the finalist pool — not
    # inferred from finalist entry order.
    size = _bracket_team_size(data)
    teams = list(data.get("bracket_teams") or [])
    teams += [[None] * size] * (4 - len(teams))
    return [list(team) + [None] * (size - len(team)) for team in teams[:4]]


def _build_bracket(data: dict, profiles_by_id: dict[str, dict], completed_games: list[DiceGame]) -> dict:
    # Bracket matches use one format (1v1 or 2v2) across the whole bracket:
    # 4 explicitly-assembled teams, one per bracket corner.
    size = _bracket_team_size(data)
    teams = _bracket_teams(data)
    bracket_game_ids = data.get("bracket_game_ids") or {}
    games_by_id = {g.id: g for g in completed_games}

    def team_slots(user_ids: list[Optional[str]]) -> list[dict]:
        return [_match_player(uid, profiles_by_id) for uid in user_ids]

    def resolve(slot_id: str, team1_ids: list[Optional[str]], team2_ids: list[Optional[str]]) -> dict:
        game = games_by_id.get(bracket_game_ids.get(slot_id))
        winner_team = game.winner_team if game is not None else None
        return {
            "id": slot_id,
            "team1": team_slots(team1_ids),
            "team2": team_slots(team2_ids),
            "game": game,
            "winner_team": winner_team,
        }

    def advancing_team(match: dict) -> list[Optional[str]]:
        if match["winner_team"] == 1:
            return [p["user_id"] for p in match["team1"]]
        if match["winner_team"] == 2:
            return [p["user_id"] for p in match["team2"]]
        return [None] * size

    semi1 = resolve("semi1", teams[0], teams[1])
    semi2 = resolve("semi2", teams[2], teams[3])
    final = resolve("final", advancing_team(semi1), advancing_team(semi2))
    champion: list[dict] = []
    if final["winner_team"] == 1:
        champion = final["team1"]
    elif final["winner_team"] == 2:
        champion = final["team2"]
    return {"semi1": semi1, "semi2": semi2, "final": final, "champion": champion}


def _match_participant_key(team1_ids: list[Optional[str]], team2_ids: list[Optional[str]]) -> Optional[tuple]:
    """Return a side-independent key for a fully populated match (1v1 or
    2v2) — both teams must be the same size with every slot filled."""
    if not team1_ids or len(team1_ids) != len(team2_ids):
        return None
    if any(not uid for uid in team1_ids + team2_ids):
        return None
    teams = [tuple(sorted(team1_ids)), tuple(sorted(team2_ids))]
    return tuple(sorted(teams))


def _reconcile_scheduled_matches(
    scheduled_matches: list[dict], completed_games: list[DiceGame]
) -> list[dict]:
    """Hide scheduled rows already represented by completed tournament games.

    This is intentionally a pure, idempotent read-time reconciliation. It
    repairs the user-visible state when the transient client-side delete after
    logging a game was skipped or failed, without mutating production data.
    Each completed game consumes only one matching scheduled row, so duplicate
    future matchups remain visible.
    """
    completed_counts: dict[tuple, int] = {}
    for game in completed_games:
        key = _match_participant_key(
            [p.user_id for p in game.players if p.team == 1],
            [p.user_id for p in game.players if p.team == 2],
        )
        if key is not None:
            completed_counts[key] = completed_counts.get(key, 0) + 1

    reconciled: list[dict] = []
    for match in scheduled_matches:
        key = _match_participant_key(
            match.get("team1_player_ids") or [], match.get("team2_player_ids") or []
        )
        if key is not None and completed_counts.get(key, 0):
            completed_counts[key] -= 1
            continue
        reconciled.append(match)
    return reconciled


def _sanitize_scheduled_match_players(match: dict) -> dict:
    """Render legacy duplicate player slots as open without mutating stored data."""
    sanitized = dict(match)
    seen: set[str] = set()
    for team_key in ("team1_player_ids", "team2_player_ids"):
        slots = []
        for user_id in match.get(team_key) or []:
            if user_id and user_id in seen:
                slots.append(None)
            else:
                slots.append(user_id)
                if user_id:
                    seen.add(user_id)
        sanitized[team_key] = slots
    return sanitized


def _tournament_from_row(
    row: dict,
    enrolled_user_ids: list[str],
    profiles_by_id: dict[str, dict],
    completed_games: Optional[list[DiceGame]] = None,
) -> DiceTournament:
    def player(user_id: str) -> dict:
        return profiles_by_id.get(user_id, {"user_id": user_id, "display_name": "Unknown"})

    data = row.get("data") or {}
    completed_games = completed_games or []
    bracket_game_ids = set((data.get("bracket_game_ids") or {}).values())
    group_stage_games = [g for g in completed_games if g.id not in bracket_game_ids]
    stored_scheduled_matches = [
        _sanitize_scheduled_match_players(match)
        for match in (data.get("scheduled_matches") or [])
    ]
    raw_scheduled_matches = _reconcile_scheduled_matches(stored_scheduled_matches, group_stage_games)
    scheduled_matches = [
        {
            "id": m["id"],
            "label": m.get("label"),
            "team1": [_match_player(uid, profiles_by_id) for uid in m.get("team1_player_ids") or [None, None]],
            "team2": [_match_player(uid, profiles_by_id) for uid in m.get("team2_player_ids") or [None, None]],
        }
        for m in raw_scheduled_matches
    ]
    return DiceTournament.model_validate(
        {
            **row,
            "description": data.get("description"),
            "hosts": [player(uid) for uid in row.get("host_user_ids") or []],
            "enrolled_players": [player(uid) for uid in enrolled_user_ids],
            "scheduled_matches": scheduled_matches,
            "completed_games": group_stage_games,
            "finalists": [player(uid) for uid in data.get("finalists") or []],
            "bracket": _build_bracket(data, profiles_by_id, completed_games),
        }
    )


def _enrolled_user_ids_for_tournaments(supabase: Client, tournament_ids: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {tid: [] for tid in tournament_ids}
    if not tournament_ids:
        return grouped
    rows = (
        supabase.table(TOURNAMENT_ENROLLMENTS_TABLE)
        .select("tournament_id, user_id")
        .in_("tournament_id", tournament_ids)
        .order("enrolled_at")
        .execute()
        .data
        or []
    )
    for row in rows:
        grouped.setdefault(row["tournament_id"], []).append(row["user_id"])
    return grouped


TOURNAMENT_COLUMNS = "id, name, starts_at, host_user_ids, data, created_by, created_at"


def list_tournaments(supabase: Client, limit: int) -> list[DiceTournament]:
    rows = (
        supabase.table(TOURNAMENTS_TABLE)
        .select(TOURNAMENT_COLUMNS)
        .order("starts_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    enrolled_by_tournament = _enrolled_user_ids_for_tournaments(supabase, [row["id"] for row in rows])
    all_user_ids = list(
        {uid for row in rows for uid in (row.get("host_user_ids") or [])}
        | {uid for ids in enrolled_by_tournament.values() for uid in ids}
        | {uid for row in rows for uid in _match_user_ids(row.get("data") or {})}
    )
    profiles_by_id = _tournament_players(supabase, all_user_ids)
    return [_tournament_from_row(row, enrolled_by_tournament.get(row["id"], []), profiles_by_id) for row in rows]


def get_tournament(supabase: Client, tournament_id: str) -> Optional[DiceTournament]:
    rows = (
        supabase.table(TOURNAMENTS_TABLE)
        .select(TOURNAMENT_COLUMNS)
        .eq("id", tournament_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    row = rows[0]
    enrolled_user_ids = _enrolled_user_ids_for_tournaments(supabase, [tournament_id]).get(tournament_id, [])
    completed_games = list_games_for_tournament(supabase, tournament_id)
    all_user_ids = list(
        set(row.get("host_user_ids") or [])
        | set(enrolled_user_ids)
        | _match_user_ids(row.get("data") or {})
        | {p.user_id for g in completed_games for p in g.players}
    )
    profiles_by_id = _tournament_players(supabase, all_user_ids)
    return _tournament_from_row(row, enrolled_user_ids, profiles_by_id, completed_games)


def _validate_host_ids(supabase: Client, host_user_ids: list[str]) -> None:
    if not host_user_ids:
        return
    existing = (
        supabase.table(PROFILES_TABLE)
        .select("user_id")
        .in_("user_id", host_user_ids)
        .execute()
        .data
        or []
    )
    if len(existing) != len(set(host_user_ids)):
        raise ValueError("all hosts must have an existing Dice profile")


def create_tournament(
    supabase: Client, created_by: str, payload: CreateTournamentRequest
) -> DiceTournament:
    host_ids = payload.host_user_ids or [created_by]
    _validate_host_ids(supabase, host_ids)

    data: dict = {}
    if payload.description:
        data["description"] = payload.description

    row = {
        "name": payload.name,
        "starts_at": payload.starts_at.isoformat(),
        "host_user_ids": host_ids,
        "data": data,
        "created_by": created_by,
    }
    response = supabase.table(TOURNAMENTS_TABLE).insert(row).execute()
    tournament = response.data[0]
    return get_tournament(supabase, tournament["id"])


def update_tournament(
    supabase: Client, tournament_id: str, payload: UpdateTournamentRequest
) -> DiceTournament:
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.starts_at is not None:
        updates["starts_at"] = payload.starts_at.isoformat()
    if payload.host_user_ids is not None:
        _validate_host_ids(supabase, payload.host_user_ids)
        updates["host_user_ids"] = payload.host_user_ids
    if payload.description is not None:
        # Read-modify-write so any other keys already living in `data` (the
        # generic, migration-free extension column) survive an edit that
        # only touches the description.
        existing_rows = (
            supabase.table(TOURNAMENTS_TABLE).select("data").eq("id", tournament_id).limit(1).execute().data
            or []
        )
        data = dict(existing_rows[0]["data"]) if existing_rows and existing_rows[0].get("data") else {}
        if payload.description:
            data["description"] = payload.description
        else:
            data.pop("description", None)
        updates["data"] = data
    supabase.table(TOURNAMENTS_TABLE).update(updates).eq("id", tournament_id).execute()

    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")
    return tournament


def delete_tournament(supabase: Client, tournament_id: str) -> None:
    supabase.table(TOURNAMENTS_TABLE).delete().eq("id", tournament_id).execute()


def enroll_in_tournament(supabase: Client, tournament_id: str, user_id: str) -> DiceTournament:
    existing = (
        supabase.table(PROFILES_TABLE).select("user_id").eq("user_id", user_id).limit(1).execute().data or []
    )
    if not existing:
        raise ValueError("user must have an existing Dice profile")
    supabase.table(TOURNAMENT_ENROLLMENTS_TABLE).upsert(
        {"tournament_id": tournament_id, "user_id": user_id}
    ).execute()
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")
    return tournament


def unenroll_from_tournament(supabase: Client, tournament_id: str, user_id: str) -> DiceTournament:
    supabase.table(TOURNAMENT_ENROLLMENTS_TABLE).delete().eq("tournament_id", tournament_id).eq(
        "user_id", user_id
    ).execute()
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")
    return tournament


def _validate_match_player_ids(supabase: Client, player_ids: list[Optional[str]]) -> None:
    ids = [pid for pid in player_ids if pid]
    if not ids:
        return
    existing = supabase.table(PROFILES_TABLE).select("user_id").in_("user_id", ids).execute().data or []
    if len(existing) != len(set(ids)):
        raise ValueError("all scheduled match players must have an existing Dice profile")


def _get_tournament_data(supabase: Client, tournament_id: str) -> dict:
    rows = (
        supabase.table(TOURNAMENTS_TABLE).select("data").eq("id", tournament_id).limit(1).execute().data or []
    )
    if not rows:
        raise ValueError("Tournament not found")
    return dict(rows[0]["data"]) if rows[0].get("data") else {}


def _save_tournament_data(supabase: Client, tournament_id: str, data: dict) -> DiceTournament:
    supabase.table(TOURNAMENTS_TABLE).update(
        {"data": data, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", tournament_id).execute()
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise ValueError("Tournament not found")
    return tournament


def add_scheduled_match(
    supabase: Client, tournament_id: str, payload: CreateScheduledMatchRequest
) -> DiceTournament:
    _validate_match_player_ids(supabase, payload.team1_player_ids + payload.team2_player_ids)

    data = _get_tournament_data(supabase, tournament_id)
    matches = list(data.get("scheduled_matches") or [])
    matches.append(
        {
            "id": str(uuid.uuid4()),
            "label": payload.label,
            "team1_player_ids": payload.team1_player_ids,
            "team2_player_ids": payload.team2_player_ids,
        }
    )
    data["scheduled_matches"] = matches
    return _save_tournament_data(supabase, tournament_id, data)


def update_scheduled_match(
    supabase: Client, tournament_id: str, match_id: str, payload: UpdateScheduledMatchRequest
) -> DiceTournament:
    _validate_match_player_ids(supabase, payload.team1_player_ids + payload.team2_player_ids)

    data = _get_tournament_data(supabase, tournament_id)
    matches = list(data.get("scheduled_matches") or [])
    for i, m in enumerate(matches):
        if m["id"] == match_id:
            matches[i] = {
                "id": match_id,
                "label": payload.label,
                "team1_player_ids": payload.team1_player_ids,
                "team2_player_ids": payload.team2_player_ids,
            }
            break
    else:
        raise ValueError("Scheduled match not found")
    data["scheduled_matches"] = matches
    return _save_tournament_data(supabase, tournament_id, data)


def delete_scheduled_match(supabase: Client, tournament_id: str, match_id: str) -> DiceTournament:
    data = _get_tournament_data(supabase, tournament_id)
    matches = [m for m in (data.get("scheduled_matches") or []) if m["id"] != match_id]
    data["scheduled_matches"] = matches
    return _save_tournament_data(supabase, tournament_id, data)


def add_finalist(supabase: Client, tournament_id: str, user_id: str) -> DiceTournament:
    _validate_match_player_ids(supabase, [user_id])

    data = _get_tournament_data(supabase, tournament_id)
    finalists = list(data.get("finalists") or [])
    if user_id in finalists:
        raise ValueError("That player is already a finalist")
    if len(finalists) >= MAX_FINALISTS:
        raise ValueError(f"The bracket only has room for {MAX_FINALISTS} finalists")
    finalists.append(user_id)
    data["finalists"] = finalists
    return _save_tournament_data(supabase, tournament_id, data)


def remove_finalist(supabase: Client, tournament_id: str, user_id: str) -> DiceTournament:
    data = _get_tournament_data(supabase, tournament_id)
    data["finalists"] = [uid for uid in (data.get("finalists") or []) if uid != user_id]

    teams = _bracket_teams(data)
    if any(user_id in team for team in teams):
        # The removed finalist was assigned to a bracket team — open up
        # just their slot rather than clearing the whole lineup, and drop
        # any bracket results already logged against the old team, since
        # they no longer correspond to who's actually on it.
        data["bracket_teams"] = [[uid if uid != user_id else None for uid in team] for team in teams]
        data["bracket_game_ids"] = {}
    return _save_tournament_data(supabase, tournament_id, data)


def set_bracket_teams(supabase: Client, tournament_id: str, payload: SetBracketTeamsRequest) -> DiceTournament:
    data = _get_tournament_data(supabase, tournament_id)
    finalist_ids = set(data.get("finalists") or [])
    # Internal storage order is [semi1.team1, semi1.team2, semi2.team1,
    # semi2.team2] (see _bracket_teams/_build_bracket) — the request's
    # team1/team3 (left side) and team2/team4 (right side) numbering gets
    # reordered to match here.
    new_teams = [
        list(payload.team1_player_ids),
        list(payload.team3_player_ids),
        list(payload.team2_player_ids),
        list(payload.team4_player_ids),
    ]
    assigned_ids = [uid for team in new_teams for uid in team if uid]
    unknown = [uid for uid in assigned_ids if uid not in finalist_ids]
    if unknown:
        raise ValueError("Only current finalists can be assigned to a bracket team")

    data["bracket_teams"] = new_teams
    # Reconfiguring the lineup invalidates any bracket results already
    # logged against the previous team assignments.
    data["bracket_game_ids"] = {}
    return _save_tournament_data(supabase, tournament_id, data)


def resolve_bracket_match(supabase: Client, tournament_id: str, slot_id: str, game_id: str) -> DiceTournament:
    if slot_id not in BRACKET_SLOTS:
        raise ValueError("Unknown bracket slot")

    game_rows = (
        _official_games(supabase.table(GAMES_TABLE).select("id, tournament_id"))
        .eq("duo_only", False)
        .eq("id", game_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not game_rows or game_rows[0].get("tournament_id") != tournament_id:
        raise ValueError("Game not found for this tournament")

    data = _get_tournament_data(supabase, tournament_id)
    bracket_game_ids = dict(data.get("bracket_game_ids") or {})
    bracket_game_ids[slot_id] = game_id
    data["bracket_game_ids"] = bracket_game_ids
    return _save_tournament_data(supabase, tournament_id, data)
