"""Dice API routes: profiles, matches, and leaderboards."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from math import isclose
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from dice.notifications import notify_ranked_game
from dice.feature_access import DiceFeature, feature_state, feature_states, is_feature_enabled, set_profile_access
from dice.live_probability import MODEL_ID, MODEL_VERSION, project_live_history, project_live_projection
from dice.live_service import append_command, create_live_match, set_membership
from dice.live_types import DiceLiveError, DiceLiveProjection, SavedRules
from dice.prediction_model import SUPPORTED_MODELS, predict_features
from dice.rating_prior import RatingSnapshot, team_average_prior
from dice.virtual_currency import (
    fixed_winner_selections,
    reconcile_match_winner_markets,
    tournament_virtual_leaderboard,
)
from dice.repository import (
    add_finalist,
    add_scheduled_match,
    create_comment,
    create_game,
    create_tournament,
    delete_comment,
    delete_game,
    delete_scheduled_match,
    delete_tournament,
    enroll_in_tournament,
    get_comment,
    get_game,
    get_head_to_head,
    get_live_result,
    get_or_create_profile,
    get_profile,
    get_rating_progress,
    get_tournament,
    list_comments,
    list_elo_leaderboard,
    list_games,
    list_games_for_user,
    list_photos,
    list_self_sink_leaderboard,
    list_sink_leaderboard,
    list_tournaments,
    remove_finalist,
    resolve_bracket_match,
    search_profiles,
    set_bracket_teams,
    unenroll_from_tournament,
    update_game,
    update_profile,
    update_scheduled_match,
    update_tournament,
)
from dice.schemas import (
    AddFinalistRequest,
    CreateCommentRequest,
    CreateGameRequest,
    CreateScheduledMatchRequest,
    CreateTournamentRequest,
    DiceGame,
    DiceFeatureState,
    DiceFeatures,
    DiceFeatureUpdate,
    DiceProfile,
    DiceTournament,
    EnrollRequest,
    GameComment,
    LeaderboardEntry,
    RatingProgress,
    ResolveBracketMatchRequest,
    SelfSinkEntry,
    SetBracketTeamsRequest,
    SinkEntry,
    UpdateGameRequest,
    UpdateDiceFeatureRequest,
    UpdateMyDiceFeatureRequest,
    UpdateProfileRequest,
    UpdateScheduledMatchRequest,
    UpdateTournamentRequest,
    LiveCommandRequest,
    LiveCreateRequest,
    LiveMatchDetailOut,
    LiveMatchOut,
    LiveMembershipOut,
    LiveReceiptOut,
    LivePredictionOut,
    LivePulseOut,
    LivePulsePointOut,
    LivePulseVirtualOut,
    VirtualBankrollOut,
    VirtualLeaderboardEntry,
    VirtualMarketOut,
    VirtualMarketCreateRequest,
    VirtualPickOut,
    VirtualPickRequest,
)

ADMIN_EMAILS = {"jason.keungg@gmail.com", "homatt999@gmail.com"}
# Backwards-compatible name used by the existing test harness and bootstrap
# documentation; authorization uses the full allowlist above.
ADMIN_EMAIL = "jason.keungg@gmail.com"

_security = HTTPBearer()
_live_security = HTTPBearer(auto_error=False)
_optional_security = HTTPBearer(auto_error=False)


class AuthedUser:
    def __init__(self, user_id: str, email: str, metadata: dict):
        self.user_id = user_id
        self.email = email
        self.metadata = metadata or {}

    @property
    def is_admin(self) -> bool:
        return self.email.lower() in ADMIN_EMAILS


def require_authenticated_user(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(_security)
) -> AuthedUser:
    try:
        user = request.app.state.supabase.auth.get_user(credentials.credentials).user
        return AuthedUser(user.id, user.email or "", user.user_metadata)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def get_optional_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_security),
) -> AuthedUser | None:
    if credentials is None:
        return None
    try:
        user = request.app.state.supabase.auth.get_user(credentials.credentials).user
        return AuthedUser(user.id, user.email or "", user.user_metadata)
    except Exception:
        return None


def _assert_can_edit_game(game: DiceGame, auth: AuthedUser) -> None:
    if auth.is_admin:
        return
    if game.created_by == auth.user_id:
        return
    if any(p.user_id == auth.user_id for p in game.players):
        return
    raise HTTPException(
        status_code=403,
        detail="Only a participant, the creator, or an admin can edit or delete this game",
    )


def _assert_can_delete_comment(comment_user_id: str, auth: AuthedUser) -> None:
    if auth.is_admin or comment_user_id == auth.user_id:
        return
    raise HTTPException(status_code=403, detail="Only the author or an admin can delete this comment")


def _assert_can_edit_tournament(tournament: DiceTournament, auth: AuthedUser) -> None:
    if auth.is_admin:
        return
    if any(h.user_id == auth.user_id for h in tournament.hosts):
        return
    raise HTTPException(status_code=403, detail="Only a host or an admin can edit or delete this tournament")


router = APIRouter()
logger = logging.getLogger(__name__)


def require_live_authenticated_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_live_security)
) -> AuthedUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    try:
        user = request.app.state.supabase.auth.get_user(credentials.credentials).user
        return AuthedUser(user.id, user.email or "", user.user_metadata)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def _require_live(request: Request, auth: AuthedUser) -> None:
    if not get_profile(request.app.state.supabase, auth.user_id):
        raise HTTPException(status_code=403, detail="dice_live.profile_required")
    if not is_feature_enabled(request.app.state.supabase, auth.user_id, DiceFeature.LIVE_REFEREE):
        raise HTTPException(status_code=403, detail="dice_live.feature_disabled")


def _live_row(request: Request, match_id: str) -> dict:
    rows = request.app.state.supabase_admin.table("dice_live_matches").select("*").eq("id", match_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="dice_live.match_not_found")
    return rows[0]


def _live_events(request: Request, match_id: str) -> list[dict]:
    return [
        item["event"]
        for item in (
            request.app.state.supabase_admin.table("dice_live_events")
            .select("event")
            .eq("match_id", match_id)
            .order("sequence")
            .execute()
            .data
            or []
        )
    ]


def _pregame_probability(row: dict) -> tuple[float, str, str, str, datetime | None]:
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


def _live_pulse_virtual(request: Request, match_id: str, user_id: str) -> LivePulseVirtualOut | None:
    markets = (
        request.app.state.supabase_admin.table("dice_virtual_markets")
        .select("*")
        .eq("live_match_id", match_id)
        .eq("kind", "match_winner")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not markets:
        return None
    market = VirtualMarketOut.model_validate(markets[0])
    picks = (
        request.app.state.supabase_admin.table("dice_virtual_picks")
        .select("*")
        .eq("market_id", market.id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    pick = VirtualPickOut.model_validate(picks[0]) if picks else None
    standing = None
    field_size = None
    try:
        leaderboard = tournament_virtual_leaderboard(request.app.state.supabase_admin, market.tournament_id)
        field_size = len(leaderboard)
        standing = next((entry for entry in leaderboard if entry["user_id"] == user_id), None)
    except Exception:
        logger.warning("Live pulse standings unavailable", exc_info=True)
    return LivePulseVirtualOut(
        tournament_id=market.tournament_id,
        market=market,
        pick=pick,
        balance=standing["balance"] if standing else None,
        rank=standing["rank"] if standing else None,
        field_size=field_size,
    )


def _live_output(request: Request, row: dict, *, detail: bool = False):
    refs = request.app.state.supabase_admin.table("dice_live_referees").select("*").eq("match_id", row["id"]).execute().data or []
    data = {key: row[key] for key in ("id", "created_by", "created_at", "team_order", "teams", "rules_snapshot", "version", "status", "score", "detail_coverage", "projection")}
    roster_ids = list(dict.fromkeys(
        player_id for team_id in row["team_order"] for player_id in row["teams"][team_id]
    ))
    profiles = (request.app.state.supabase_admin.table("dice_profiles")
        .select("user_id, display_name, avatar_url, elo_rating, games_played, wins, losses, sinks, self_sinks")
        .in_("user_id", roster_ids).execute().data or [])
    data["player_names"] = {
        profile["user_id"]: profile["display_name"] for profile in profiles
        if profile.get("display_name")
    }
    data["player_avatars"] = {
        profile["user_id"]: profile["avatar_url"] for profile in profiles
        if profile.get("avatar_url")
    }
    data["player_stats"] = {
        profile["user_id"]: {
            key: profile.get(key, 0)
            for key in ("elo_rating", "games_played", "wins", "losses", "sinks", "self_sinks")
        }
        for profile in profiles
    }
    data["referees"] = refs
    if detail:
        data["events"] = _live_events(request, row["id"])
        return LiveMatchDetailOut.model_validate(data)
    return LiveMatchOut.model_validate(data)


def _command_error(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        detail = error.errors()[0]
        message = detail.get("msg", "invalid command")
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        return HTTPException(status_code=422, detail={
            "code": "dice_live.invalid_command", "message": message
        })
    raw = getattr(error, "message", str(error))
    if "stale_version" in raw:
        details = getattr(error, "details", "") or ""
        try:
            details = json.loads(details)
        except (TypeError, json.JSONDecodeError):
            details = {}
        return HTTPException(status_code=409, detail={"code": "dice_live.stale_version", **details})
    if "command_id_conflict" in raw:
        return HTTPException(status_code=409, detail={"code": "dice_live.command_id_conflict"})
    if "referee_not_joined" in raw:
        return HTTPException(status_code=403, detail={"code": "dice_live.referee_not_joined"})
    if "match_not_found" in raw:
        return HTTPException(status_code=404, detail={"code": "dice_live.match_not_found"})
    return HTTPException(status_code=422, detail={"code": getattr(error, "code", "dice_live.invalid_command"), "message": str(error)})


@router.post("/live/games", response_model=LiveMatchOut)
def post_live_game(request: Request, payload: LiveCreateRequest, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    try:
        row = create_live_match(request.app.state.supabase_admin, auth.user_id, payload.team_order, payload.teams, payload.rules_snapshot)
    except DiceLiveError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message})
    return _live_output(request, row)


@router.get("/live/games", response_model=list[LiveMatchOut])
def get_live_games(request: Request, state: Literal["ongoing"] = Query("ongoing"), auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    rows = request.app.state.supabase_admin.table("dice_live_matches").select("*").in_("status", ["active", "awaiting_replay", "ready_to_finish"]).order("updated_at", desc=True).execute().data or []
    return [_live_output(request, row) for row in rows]


@router.get("/live/games/{match_id}", response_model=LiveMatchDetailOut)
def get_live_game(request: Request, match_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    return _live_output(request, _live_row(request, match_id), detail=True)


@router.get("/live/games/{match_id}/prediction", response_model=LivePredictionOut)
def get_live_prediction(request: Request, match_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    """Return an optional score-derived estimate from the canonical live snapshot."""
    _require_live(request, auth)
    row = _live_row(request, match_id)
    try:
        pregame_probability, pregame_source, pregame_model_id, pregame_model_version, input_timestamp = _pregame_probability(row)
        result = project_live_projection(
            DiceLiveProjection.model_validate(row["projection"]),
            SavedRules.model_validate(row["rules_snapshot"]),
            match_version=row["version"],
            # Ratings are intentionally not inferred from client input. Until the
            # versioned rating snapshot is wired, the honest prior is neutral.
            pregame_team1_probability=pregame_probability,
        )
    except (ValidationError, DiceLiveError) as error:
        raise HTTPException(status_code=422, detail={"code": "dice_live.prediction_unavailable", "message": str(error)})
    return LivePredictionOut(
        status="available",
        match_version=result.match_version,
        model_id=result.model_id,
        model_version=result.model_version,
        team1_win_probability=result.team1,
        team2_win_probability=result.team2,
        pregame_source=pregame_source,
        pregame_model_id=pregame_model_id,
        pregame_model_version=pregame_model_version,
        input_timestamp=input_timestamp,
    )


@router.get("/live/games/{match_id}/pulse", response_model=LivePulseOut)
def get_live_pulse(request: Request, match_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    """Return the correction-aware game story and optional personal pick context."""
    _require_live(request, auth)
    row = _live_row(request, match_id)
    events = _live_events(request, match_id)
    try:
        pregame_probability, pregame_source, pregame_model_id, pregame_model_version, input_timestamp = _pregame_probability(row)
        match = {"match_id": row["id"], "team_order": row["team_order"], "teams": row["teams"]}
        history = project_live_history(
            match,
            row["rules_snapshot"],
            events,
            pregame_team1_probability=pregame_probability,
        )
    except (ValidationError, DiceLiveError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "dice_live.pulse_unavailable", "message": str(error)},
        )
    try:
        virtual = _live_pulse_virtual(request, match_id, auth.user_id)
    except Exception:
        logger.warning("Live pulse pick context unavailable", exc_info=True)
        virtual = None
    return LivePulseOut(
        match_version=row["version"],
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        pregame_source=pregame_source,
        pregame_model_id=pregame_model_id,
        pregame_model_version=pregame_model_version,
        input_timestamp=input_timestamp,
        points=[LivePulsePointOut(
            match_version=point.match_version,
            score=list(point.score),
            team1_win_probability=point.team1,
            team2_win_probability=point.team2,
            swing=point.swing,
            kind=point.kind,
            outcome=point.outcome,
            thrower_id=point.thrower_id,
            fifa_finish=point.fifa_finish,
            fifa_actor_id=point.fifa_actor_id,
        ) for point in history],
        virtual=virtual,
    )


@router.post("/virtual/tournaments/{tournament_id}/bankroll", response_model=VirtualBankrollOut)
def open_virtual_bankroll(request: Request, tournament_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    try:
        balance = request.app.state.supabase_admin.rpc("dice_virtual_open_bankroll", {
            "p_tournament_id": tournament_id, "p_user_id": auth.user_id, "p_amount": 1000,
        }).execute().data
    except Exception as error:
        code = "dice_virtual.not_enrolled" if "not_enrolled" in str(error) else "dice_virtual.bankroll_unavailable"
        raise HTTPException(status_code=403 if code.endswith("not_enrolled") else 422, detail={"code": code})
    return VirtualBankrollOut(tournament_id=tournament_id, balance=balance)


@router.get(
    "/virtual/tournaments/{tournament_id}/leaderboard",
    response_model=list[VirtualLeaderboardEntry],
)
def get_virtual_leaderboard(
    request: Request,
    tournament_id: str,
    auth: AuthedUser = Depends(require_live_authenticated_user),
):
    _require_live(request, auth)
    return tournament_virtual_leaderboard(request.app.state.supabase_admin, tournament_id)


@router.get("/virtual/tournaments/{tournament_id}/markets", response_model=list[VirtualMarketOut])
def get_virtual_markets(request: Request, tournament_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    return (request.app.state.supabase_admin.table("dice_virtual_markets").select("*")
        .eq("tournament_id", tournament_id).order("created_at", desc=True).execute().data or [])


@router.get("/virtual/tournaments/{tournament_id}/picks", response_model=list[VirtualPickOut])
def get_virtual_picks(request: Request, tournament_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    """Return only the caller's locked picks for a refresh-safe portfolio."""
    _require_live(request, auth)
    return (request.app.state.supabase_admin.table("dice_virtual_picks").select("*")
        .eq("tournament_id", tournament_id).eq("user_id", auth.user_id)
        .order("created_at", desc=True).execute().data or [])


@router.post("/virtual/tournaments/{tournament_id}/markets", response_model=VirtualMarketOut)
def create_virtual_market(request: Request, tournament_id: str, payload: VirtualMarketCreateRequest,
                          auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    row = _live_row(request, payload.live_match_id)
    if row["version"] != 0 or row["status"] != "active":
        raise HTTPException(status_code=409, detail={"code": "dice_virtual.market_already_started"})
    enrolled = (request.app.state.supabase_admin.table("dice_tournament_enrollments")
        .select("user_id").eq("tournament_id", tournament_id).execute().data or [])
    enrolled_ids = {item["user_id"] for item in enrolled}
    roster_ids = {player for team_id in row["team_order"] for player in row["teams"][team_id]}
    if auth.user_id not in enrolled_ids or not roster_ids.issubset(enrolled_ids):
        raise HTTPException(status_code=403, detail={"code": "dice_virtual.not_enrolled"})
    try:
        probability, source, model_id, model_version, _ = _pregame_probability(row)
        if source == "neutral_fallback":
            raise ValueError("versioned prediction snapshot required")
        selections = fixed_winner_selections(row["team_order"], probability)
    except (KeyError, TypeError, ValueError, DiceLiveError):
        raise HTTPException(status_code=422, detail={"code": "dice_virtual.prediction_snapshot_required"})
    created = request.app.state.supabase_admin.table("dice_virtual_markets").insert({
        "tournament_id": tournament_id, "live_match_id": row["id"], "kind": "match_winner",
        "model_id": model_id, "model_version": model_version,
        "match_version": row["version"], "selections": selections,
    }).execute().data
    return created[0]


@router.post("/virtual/tournaments/{tournament_id}/markets/{market_id}/picks", response_model=VirtualPickOut)
def place_virtual_pick(request: Request, tournament_id: str, market_id: int, payload: VirtualPickRequest,
                       auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    try:
        return request.app.state.supabase_admin.rpc("dice_virtual_place_pick", {
            "p_tournament_id": tournament_id, "p_market_id": market_id,
            "p_user_id": auth.user_id, "p_client_pick_id": payload.client_pick_id,
            "p_selection": payload.selection, "p_stake": payload.stake,
        }).execute().data
    except Exception as error:
        raw = str(error)
        for code, status in (("insufficient_balance", 409), ("pick_id_conflict", 409),
                             ("market_closed", 409), ("market_not_found", 404),
                             ("invalid_selection", 422)):
            if code in raw:
                raise HTTPException(status_code=status, detail={"code": f"dice_virtual.{code}"})
        raise HTTPException(status_code=422, detail={"code": "dice_virtual.pick_rejected"})


@router.put("/live/games/{match_id}/referees/me", response_model=LiveMembershipOut)
def join_live_game(request: Request, match_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    _live_row(request, match_id)
    set_membership(request.app.state.supabase_admin, match_id, auth.user_id, True)
    return LiveMembershipOut(match_id=match_id, user_id=auth.user_id, joined=True)


@router.delete("/live/games/{match_id}/referees/me", response_model=LiveMembershipOut)
def leave_live_game(request: Request, match_id: str, auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    _live_row(request, match_id)
    set_membership(request.app.state.supabase_admin, match_id, auth.user_id, False)
    return LiveMembershipOut(match_id=match_id, user_id=auth.user_id, joined=False)


@router.post("/live/games/{match_id}/commands", response_model=LiveReceiptOut)
def post_live_command(request: Request, match_id: str, payload: dict = Body(...), auth: AuthedUser = Depends(require_live_authenticated_user)):
    _require_live(request, auth)
    _live_row(request, match_id)
    try:
        command = LiveCommandRequest.model_validate(payload)
        receipt = append_command(request.app.state.supabase_admin, match_id, auth.user_id, command)
    except ValidationError as error:
        raise _command_error(error)
    except DiceLiveError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message, "event_id": error.event_id, "sequence": error.sequence})
    except Exception as error:
        raise _command_error(error)
    try:
        current_row = _live_row(request, match_id)
        current_result = get_live_result(request.app.state.supabase_admin, match_id)
        reconcile_match_winner_markets(
            request.app.state.supabase_admin,
            match_id,
            current_row["team_order"],
            current_row["version"],
            current_result,
        )
    except Exception:
        # The command is already durable. Betting must never make scoring look
        # failed or tempt the client to submit the same event again.
        logger.exception("Virtual Dice reconciliation failed for live match %s", match_id)
    return receipt


@router.get("/me", response_model=DiceProfile)
def get_my_profile(
    request: Request, auth: AuthedUser = Depends(require_authenticated_user)
) -> DiceProfile:
    default_name = auth.metadata.get("full_name") or auth.metadata.get("name") or "Player"
    default_avatar = auth.metadata.get("avatar_url")
    return get_or_create_profile(
        request.app.state.supabase,
        auth.user_id,
        default_name,
        default_avatar,
    )


@router.get("/me/features", response_model=DiceFeatures)
def get_my_features(
    request: Request, auth: AuthedUser = Depends(require_authenticated_user)
) -> DiceFeatures:
    return DiceFeatures.model_validate(
        feature_states(request.app.state.supabase, auth.user_id)
    )


@router.put("/me/features/{feature}", response_model=DiceFeatures)
def put_my_feature(
    request: Request,
    feature: DiceFeature,
    payload: UpdateMyDiceFeatureRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceFeatures:
    if not get_profile(request.app.state.supabase, auth.user_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    set_profile_access(request.app.state.supabase_admin, auth.user_id, feature, payload.enabled)
    return DiceFeatures.model_validate(
        feature_states(request.app.state.supabase, auth.user_id)
    )


@router.put("/admin/features/{user_id}", response_model=DiceFeatureUpdate)
def put_profile_feature(
    request: Request,
    user_id: str,
    payload: UpdateDiceFeatureRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceFeatureUpdate:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can manage feature access")
    if not get_profile(request.app.state.supabase, user_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    set_profile_access(request.app.state.supabase_admin, user_id, payload.feature, payload.enabled)
    state = feature_state(request.app.state.supabase, user_id, payload.feature)
    return DiceFeatureUpdate(
        user_id=user_id,
        feature=payload.feature,
        state=DiceFeatureState.model_validate(state),
    )


@router.put("/me", response_model=DiceProfile)
def put_my_profile(
    request: Request,
    payload: UpdateProfileRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceProfile:
    target_user_id = auth.user_id
    if payload.user_id and payload.user_id != auth.user_id:
        if not auth.is_admin:
            raise HTTPException(status_code=403, detail="Only an admin can edit another profile")
        target_user_id = payload.user_id
    try:
        return update_profile(
            request.app.state.supabase,
            target_user_id,
            payload.display_name,
            payload.avatar_url,
            payload.hide_from_leaderboard,
            payload.phone_number,
            payload.sms_notifications_enabled,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.get("/profiles/search", response_model=list[DiceProfile])
def get_profiles_search(
    request: Request, q: str = Query(default=""), limit: int = Query(default=20, ge=1, le=500)
) -> list[DiceProfile]:
    return search_profiles(request.app.state.supabase, q, limit)


@router.get("/profiles/{user_id}", response_model=DiceProfile)
def get_profile_by_id(
    request: Request,
    user_id: str,
    viewer: AuthedUser | None = Depends(get_optional_authenticated_user),
) -> DiceProfile:
    profile = get_profile(request.app.state.supabase, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if viewer is not None and viewer.user_id != user_id:
        head_to_head = get_head_to_head(request.app.state.supabase, viewer.user_id, user_id)
        profile = profile.model_copy(update={"head_to_head": head_to_head})
    return profile


@router.get("/profiles/{user_id}/games", response_model=list[DiceGame])
def get_profile_games(
    request: Request, user_id: str, limit: int = Query(default=50, ge=1, le=200)
) -> list[DiceGame]:
    return list_games_for_user(request.app.state.supabase, user_id, limit)


@router.get("/profiles/{user_id}/rating-progress", response_model=RatingProgress)
def get_profile_rating_progress(request: Request, user_id: str) -> RatingProgress:
    try:
        progress = get_rating_progress(request.app.state.supabase, user_id)
    except (RuntimeError, ValueError):
        raise HTTPException(status_code=503, detail="Rating progress is being refreshed") from None
    if progress is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return progress


@router.get("/leaderboard/elo", response_model=list[LeaderboardEntry])
def get_elo_leaderboard(
    request: Request,
    limit: int = Query(default=5, ge=1, le=500),
    include_provisional: bool = Query(default=False),
) -> list[LeaderboardEntry]:
    return list_elo_leaderboard(request.app.state.supabase, limit, include_provisional)


@router.get("/leaderboard/self-sinks", response_model=list[SelfSinkEntry])
def get_self_sink_leaderboard(
    request: Request,
    limit: int = Query(default=5, ge=1, le=500),
    nonzero_only: bool = Query(default=True),
) -> list[SelfSinkEntry]:
    return list_self_sink_leaderboard(request.app.state.supabase, limit, nonzero_only)


@router.get("/leaderboard/sinks", response_model=list[SinkEntry])
def get_sink_leaderboard(
    request: Request,
    limit: int = Query(default=5, ge=1, le=500),
    nonzero_only: bool = Query(default=True),
) -> list[SinkEntry]:
    return list_sink_leaderboard(request.app.state.supabase, limit, nonzero_only)


@router.get("/games", response_model=list[DiceGame])
def get_games(
    request: Request,
    limit: int = Query(default=5, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DiceGame]:
    return list_games(request.app.state.supabase, limit, offset)


@router.get("/games/{game_id}", response_model=DiceGame)
def get_game_by_id(request: Request, game_id: str) -> DiceGame:
    game = get_game(request.app.state.supabase, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.post("/games", response_model=DiceGame)
def post_game(
    request: Request,
    payload: CreateGameRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceGame:
    try:
        created = create_game(
            request.app.state.supabase, auth.user_id, payload, mutation_id=idempotency_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not created.replayed:
        background_tasks.add_task(
            notify_ranked_game,
            request.app.state.supabase,
            created.game,
            request.app.state.runtime_policy,
        )
    return created.game


@router.put("/games/{game_id}", response_model=DiceGame)
def put_game(
    request: Request,
    game_id: str,
    payload: UpdateGameRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceGame:
    supabase = request.app.state.supabase
    existing = get_game(supabase, game_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Game not found")
    _assert_can_edit_game(existing, auth)
    try:
        return update_game(supabase, game_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/games/{game_id}")
def delete_game_by_id(
    request: Request, game_id: str, auth: AuthedUser = Depends(require_authenticated_user)
) -> dict:
    supabase = request.app.state.supabase
    existing = get_game(supabase, game_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Game not found")
    _assert_can_edit_game(existing, auth)
    try:
        delete_game(supabase, game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"deleted": True}


@router.get("/photos", response_model=list[GameComment])
def get_photos(
    request: Request, limit: int = Query(default=100, ge=1, le=500)
) -> list[GameComment]:
    return list_photos(request.app.state.supabase, limit)


@router.get("/games/{game_id}/comments", response_model=list[GameComment])
def get_game_comments(request: Request, game_id: str) -> list[GameComment]:
    supabase = request.app.state.supabase
    if not get_game(supabase, game_id):
        raise HTTPException(status_code=404, detail="Game not found")
    return list_comments(supabase, game_id)


@router.post("/games/{game_id}/comments", response_model=GameComment)
def post_game_comment(
    request: Request,
    game_id: str,
    payload: CreateCommentRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> GameComment:
    supabase = request.app.state.supabase
    if not get_game(supabase, game_id):
        raise HTTPException(status_code=404, detail="Game not found")
    return create_comment(supabase, game_id, auth.user_id, payload.body, payload.image_url)


@router.delete("/comments/{comment_id}")
def delete_game_comment(
    request: Request, comment_id: str, auth: AuthedUser = Depends(require_authenticated_user)
) -> dict:
    supabase = request.app.state.supabase
    comment = get_comment(supabase, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    _assert_can_delete_comment(comment["user_id"], auth)
    delete_comment(supabase, comment_id)
    return {"deleted": True}


@router.get("/tournaments", response_model=list[DiceTournament])
def get_tournaments(
    request: Request, limit: int = Query(default=20, ge=1, le=200)
) -> list[DiceTournament]:
    return list_tournaments(request.app.state.supabase, limit)


@router.get("/tournaments/{tournament_id}", response_model=DiceTournament)
def get_tournament_by_id(request: Request, tournament_id: str) -> DiceTournament:
    tournament = get_tournament(request.app.state.supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


@router.post("/tournaments", response_model=DiceTournament)
def post_tournament(
    request: Request,
    payload: CreateTournamentRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can create a tournament")
    try:
        return create_tournament(request.app.state.supabase, auth.user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/tournaments/{tournament_id}", response_model=DiceTournament)
def put_tournament(
    request: Request,
    tournament_id: str,
    payload: UpdateTournamentRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    existing = get_tournament(supabase, tournament_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(existing, auth)
    try:
        return update_tournament(supabase, tournament_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tournaments/{tournament_id}")
def delete_tournament_by_id(
    request: Request, tournament_id: str, auth: AuthedUser = Depends(require_authenticated_user)
) -> dict:
    supabase = request.app.state.supabase
    existing = get_tournament(supabase, tournament_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(existing, auth)
    delete_tournament(supabase, tournament_id)
    return {"deleted": True}


@router.post("/tournaments/{tournament_id}/enroll", response_model=DiceTournament)
def post_tournament_enroll(
    request: Request,
    tournament_id: str,
    payload: EnrollRequest = EnrollRequest(),
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    target_user_id = auth.user_id
    if payload.user_id and payload.user_id != auth.user_id:
        # Adding someone else requires host/admin; self-enroll needs no check.
        _assert_can_edit_tournament(tournament, auth)
        target_user_id = payload.user_id
    try:
        return enroll_in_tournament(supabase, tournament_id, target_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tournaments/{tournament_id}/enroll", response_model=DiceTournament)
def delete_tournament_enroll(
    request: Request,
    tournament_id: str,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    if not get_tournament(supabase, tournament_id):
        raise HTTPException(status_code=404, detail="Tournament not found")
    try:
        return unenroll_from_tournament(supabase, tournament_id, auth.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tournaments/{tournament_id}/matches", response_model=DiceTournament)
def post_scheduled_match(
    request: Request,
    tournament_id: str,
    payload: CreateScheduledMatchRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return add_scheduled_match(supabase, tournament_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/tournaments/{tournament_id}/matches/{match_id}", response_model=DiceTournament)
def put_scheduled_match(
    request: Request,
    tournament_id: str,
    match_id: str,
    payload: UpdateScheduledMatchRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return update_scheduled_match(supabase, tournament_id, match_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tournaments/{tournament_id}/matches/{match_id}", response_model=DiceTournament)
def delete_scheduled_match_by_id(
    request: Request,
    tournament_id: str,
    match_id: str,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return delete_scheduled_match(supabase, tournament_id, match_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tournaments/{tournament_id}/finalists", response_model=DiceTournament)
def post_finalist(
    request: Request,
    tournament_id: str,
    payload: AddFinalistRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return add_finalist(supabase, tournament_id, payload.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tournaments/{tournament_id}/finalists/{user_id}", response_model=DiceTournament)
def delete_finalist(
    request: Request,
    tournament_id: str,
    user_id: str,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return remove_finalist(supabase, tournament_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/tournaments/{tournament_id}/bracket/teams", response_model=DiceTournament)
def put_bracket_teams(
    request: Request,
    tournament_id: str,
    payload: SetBracketTeamsRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    _assert_can_edit_tournament(tournament, auth)
    try:
        return set_bracket_teams(supabase, tournament_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tournaments/{tournament_id}/bracket/{slot_id}/resolve", response_model=DiceTournament)
def post_resolve_bracket_match(
    request: Request,
    tournament_id: str,
    slot_id: str,
    payload: ResolveBracketMatchRequest,
    auth: AuthedUser = Depends(require_authenticated_user),
) -> DiceTournament:
    # Same permission model as logging a game itself (see post_game): any
    # signed-in user can record a bracket result, not just the tournament's
    # host or an admin — a player reporting their own bracket match is the
    # common case, mirroring how entering a group-stage result works.
    supabase = request.app.state.supabase
    tournament = get_tournament(supabase, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    try:
        return resolve_bracket_match(supabase, tournament_id, slot_id, payload.game_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
