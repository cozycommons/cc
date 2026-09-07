"""Pydantic models for the Dice team score/ELO tracker API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from dice.elo import PROVISIONAL_GAMES_THRESHOLD
from dice.feature_access import DiceFeature
from dice.live_service import LiveCommand

STARTING_ELO = 1500
PHONE_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class HeadToHeadRecord(BaseModel):
    opponent_wins: int = 0
    opponent_losses: int = 0
    teammate_wins: int = 0
    teammate_losses: int = 0

    @computed_field
    @property
    def total_games(self) -> int:
        return self.opponent_wins + self.opponent_losses + self.teammate_wins + self.teammate_losses


class _ProvisionalRatingMixin(BaseModel):
    ranked_games_played: int = 0

    @computed_field
    @property
    def is_provisional(self) -> bool:
        """True while the player is still in their placement games.

        A provisional ELO hasn't played enough ranked games to be trusted,
        so it's excluded from the home page's leaderboard preview and
        flagged wherever it's shown instead (own profile, full leaderboard).
        """
        return self.ranked_games_played < PROVISIONAL_GAMES_THRESHOLD

    @computed_field
    @property
    def placement_games_remaining(self) -> int:
        return max(0, PROVISIONAL_GAMES_THRESHOLD - self.ranked_games_played)


class DiceProfile(_ProvisionalRatingMixin):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    elo_rating: int = STARTING_ELO
    rating_deviation: float
    elo_model_version: str
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    ranked_wins: int = 0
    ranked_losses: int = 0
    normal_wins: int = 0
    normal_losses: int = 0
    self_sinks: int = 0
    sinks: int = 0
    hide_from_leaderboard: bool = False
    phone_number: Optional[str] = None
    sms_notifications_enabled: bool = False
    head_to_head: Optional[HeadToHeadRecord] = None


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    avatar_url: Optional[str] = None
    hide_from_leaderboard: Optional[bool] = None
    phone_number: Optional[str] = None
    sms_notifications_enabled: Optional[bool] = None
    user_id: Optional[str] = None  # admin-only override of which profile to edit

    @field_validator("phone_number")
    @classmethod
    def _validate_phone_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not PHONE_E164_RE.match(stripped):
            raise ValueError("phone number must be in E.164 format, e.g. +14155551234")
        return stripped


class DiceFeatureState(BaseModel):
    opted_in: bool = False
    effective: bool = False


class DiceFeatures(BaseModel):
    dice_live_referee: DiceFeatureState = Field(default_factory=DiceFeatureState)


class UpdateMyDiceFeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class UpdateDiceFeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: DiceFeature
    enabled: bool


class DiceFeatureUpdate(BaseModel):
    user_id: str
    feature: DiceFeature
    state: DiceFeatureState


class LiveCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    team_order: list[str] = Field(min_length=2, max_length=2)
    teams: dict[str, list[str]]
    rules_snapshot: dict

    @model_validator(mode="after")
    def validate_roster(self) -> "LiveCreateRequest":
        if set(self.team_order) != set(self.teams) or any(not self.teams[team] for team in self.team_order):
            raise ValueError("team_order must name two nonempty teams")
        players = [player for team in self.team_order for player in self.teams[team]]
        if len(players) != 4 or len(set(players)) != 4:
            raise ValueError("a live match requires four distinct 2v2 players")
        return self


class LiveCommandRequest(LiveCommand):
    pass


class LiveRefereeOut(BaseModel):
    match_id: str
    user_id: str
    joined_at: datetime
    left_at: datetime | None = None


class LiveMatchOut(BaseModel):
    id: str
    created_by: str
    created_at: datetime
    team_order: list[str]
    teams: dict[str, list[str]]
    rules_snapshot: dict
    version: int
    status: str
    score: list[int]
    detail_coverage: str
    projection: dict
    player_names: dict[str, str] = Field(default_factory=dict)
    player_avatars: dict[str, str] = Field(default_factory=dict)
    player_stats: dict[str, dict] = Field(default_factory=dict)
    referees: list[LiveRefereeOut] = Field(default_factory=list)


class LiveMatchDetailOut(LiveMatchOut):
    events: list[dict] = Field(default_factory=list)


class LiveMembershipOut(BaseModel):
    match_id: str
    user_id: str
    joined: bool


class LiveReceiptOut(BaseModel):
    accepted_version: int
    first_sequence: int
    last_sequence: int
    projection: dict
    official_result: dict | None = None


class VirtualBankrollOut(BaseModel):
    tournament_id: str
    balance: int


class VirtualLeaderboardEntry(BaseModel):
    rank: int = Field(gt=0)
    user_id: str
    display_name: str
    balance: int


class VirtualPickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_pick_id: str = Field(min_length=1, max_length=100)
    selection: str = Field(min_length=1, max_length=100)
    stake: int = Field(gt=0, le=1_000_000)


class VirtualPickOut(BaseModel):
    id: int
    tournament_id: str
    market_id: int
    user_id: str
    client_pick_id: str
    selection: str
    stake: int
    potential_return: int
    locked_probability_millionths: int
    quote_model_id: str
    quote_model_version: str
    quote_match_version: int
    status: str
    settled_at: datetime | None = None


class VirtualMarketOut(BaseModel):
    id: int
    tournament_id: str
    live_match_id: str
    kind: str
    status: str
    model_id: str
    model_version: str
    match_version: int
    selections: dict
    settled_at: datetime | None = None
    settled_selection: str | None = None
    settlement_revision: int = 0


class VirtualMarketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    live_match_id: str


class LivePredictionOut(BaseModel):
    status: Literal["available"]
    match_version: int = Field(gt=0)
    model_id: str
    model_version: str
    team1_win_probability: float = Field(ge=0, le=1)
    team2_win_probability: float = Field(ge=0, le=1)
    pregame_source: Literal["neutral_fallback", "legacy_elo_snapshot", "independent_model_snapshot"]
    pregame_model_id: str
    pregame_model_version: str
    input_timestamp: datetime | None = None


class LivePulsePointOut(BaseModel):
    match_version: int = Field(ge=0)
    score: list[int] = Field(min_length=2, max_length=2)
    team1_win_probability: float = Field(ge=0, le=1)
    team2_win_probability: float = Field(ge=0, le=1)
    swing: float = Field(ge=-1, le=1)
    kind: Literal["start", "play", "correction", "reopen", "retoss", "score_update", "finish"]
    outcome: str | None = None
    thrower_id: str | None = None
    fifa_finish: Literal["goal", "kick_catch", "goal_saved"] | None = None
    fifa_actor_id: str | None = None


class LivePulseVirtualOut(BaseModel):
    tournament_id: str
    market: VirtualMarketOut
    pick: VirtualPickOut | None = None
    balance: int | None = None
    rank: int | None = Field(default=None, gt=0)
    field_size: int | None = Field(default=None, ge=0)


class LivePulseOut(BaseModel):
    match_version: int = Field(ge=0)
    model_id: str
    model_version: str
    pregame_source: Literal["neutral_fallback", "legacy_elo_snapshot", "independent_model_snapshot"]
    pregame_model_id: str
    pregame_model_version: str
    input_timestamp: datetime | None = None
    points: list[LivePulsePointOut]
    virtual: LivePulseVirtualOut | None = None


class GamePlayerIn(BaseModel):
    user_id: str
    team: int
    counts_for_group_stage: bool = True
    self_sinks: int = Field(default=0, ge=0)
    sinks: int = Field(default=0, ge=0)

    @field_validator("team")
    @classmethod
    def _validate_team(cls, value: int) -> int:
        if value not in (1, 2):
            raise ValueError("team must be 1 or 2")
        return value


class GamePlayerOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    team: int
    counts_for_group_stage: bool = True
    self_sinks: int
    sinks: int
    elo_before: Optional[int] = None
    elo_after: Optional[int] = None
    rating_deviation_before: Optional[float] = None
    rating_deviation_after: Optional[float] = None


class CreateGameRequest(BaseModel):
    ranked: bool = False
    team1_score: int = Field(ge=0)
    team2_score: int = Field(ge=0)
    played_at: Optional[datetime] = None
    tournament_id: Optional[str] = None
    players: list[GamePlayerIn]

    @field_validator("players")
    @classmethod
    def _validate_players(cls, value: list[GamePlayerIn]) -> list[GamePlayerIn]:
        if len(value) not in (2, 4):
            raise ValueError("a game requires either 2 players (1v1) or 4 players (2v2)")
        user_ids = [p.user_id for p in value]
        if len(set(user_ids)) != len(value):
            raise ValueError("all players must be distinct")
        team1 = [p for p in value if p.team == 1]
        team2 = [p for p in value if p.team == 2]
        per_team = len(value) // 2
        if len(team1) != per_team or len(team2) != per_team:
            raise ValueError(f"each team must have exactly {per_team} player(s)")
        return value


class UpdateGameRequest(CreateGameRequest):
    pass


class DiceGame(BaseModel):
    id: str
    created_by: str
    ranked: bool
    team1_score: int
    team2_score: int
    winner_team: Optional[int] = None
    played_at: datetime
    created_at: datetime
    tournament_id: Optional[str] = None
    players: list[GamePlayerOut]


class LeaderboardEntry(_ProvisionalRatingMixin):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    elo_rating: int
    games_played: int
    wins: int
    losses: int
    rank: Optional[int] = Field(default=None, gt=0)
    is_tied: bool = False


class RatingProgressPoint(BaseModel):
    game_id: str
    played_at: datetime
    rating_before: int
    rating_after: int
    delta: int
    rank_before: Optional[int] = Field(default=None, gt=0)
    rank_after: Optional[int] = Field(default=None, gt=0)
    rank_change: Optional[int] = None
    is_personal_best: bool = False


class RatingProgress(BaseModel):
    rating_system_version: str
    rank_scope: Literal["current_visible_established_field"]
    current_rating: int
    current_rank: Optional[int] = Field(default=None, gt=0)
    current_rank_tied: bool = False
    field_size: int = Field(ge=0)
    is_provisional: bool
    placement_games_remaining: int = Field(ge=0)
    personal_best: int
    last_delta: Optional[int] = None
    last_rank_change: Optional[int] = None
    history: list[RatingProgressPoint]


class SelfSinkEntry(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    self_sinks: int


class SinkEntry(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    sinks: int


class CreateCommentRequest(BaseModel):
    body: Optional[str] = Field(default=None, max_length=2000)
    image_url: Optional[str] = None

    @field_validator("body")
    @classmethod
    def _strip_body(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _validate_has_content(self) -> "CreateCommentRequest":
        if not self.body and not self.image_url:
            raise ValueError("a comment needs text, an image, or both")
        return self


class GameComment(BaseModel):
    id: str
    game_id: str
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime


class TournamentPlayer(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None


class CreateTournamentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    host_user_ids: list[str] = Field(default_factory=list)
    description: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped

    @field_validator("host_user_ids")
    @classmethod
    def _dedupe_hosts(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class UpdateTournamentRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    starts_at: Optional[datetime] = None
    host_user_ids: Optional[list[str]] = None
    description: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank")
        return stripped

    @field_validator("host_user_ids")
    @classmethod
    def _dedupe_hosts(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class EnrollRequest(BaseModel):
    # Self-enroll leaves this unset; a host/admin adding someone else sets it.
    user_id: Optional[str] = None


class ScheduledMatchPlayer(BaseModel):
    user_id: Optional[str] = None
    display_name: str = "TBD"
    avatar_url: Optional[str] = None


class ScheduledMatch(BaseModel):
    id: str
    label: Optional[str] = None
    team1: list[ScheduledMatchPlayer]
    team2: list[ScheduledMatchPlayer]


class CreateScheduledMatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=60)
    team1_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])
    team2_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])

    @field_validator("team1_player_ids", "team2_player_ids")
    @classmethod
    def _one_or_two_slots(cls, value: list[Optional[str]]) -> list[Optional[str]]:
        if len(value) not in (1, 2):
            raise ValueError("each team needs 1 player slot (1v1) or 2 (2v2) — use null for TBD")
        return value

    @model_validator(mode="after")
    def _teams_match_format(self) -> "CreateScheduledMatchRequest":
        if len(self.team1_player_ids) != len(self.team2_player_ids):
            raise ValueError("both teams must have the same number of slots (1v1 or 2v2)")
        return self

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class UpdateScheduledMatchRequest(CreateScheduledMatchRequest):
    pass


class AddFinalistRequest(BaseModel):
    user_id: str


class BracketSlot(BaseModel):
    user_id: Optional[str] = None
    display_name: str = "TBD"
    avatar_url: Optional[str] = None


class BracketMatch(BaseModel):
    id: str
    # Each side is a team of 1 (1v1) or 2 (2v2) players, consistent across
    # the whole bracket — TBD-filled if the corner is still open.
    team1: list[BracketSlot]
    team2: list[BracketSlot]
    game: Optional[DiceGame] = None
    winner_team: Optional[int] = None


class Bracket(BaseModel):
    semi1: BracketMatch
    semi2: BracketMatch
    final: BracketMatch
    champion: list[BracketSlot] = Field(default_factory=list)


class ResolveBracketMatchRequest(BaseModel):
    game_id: str


class SetBracketTeamsRequest(BaseModel):
    # One entry per bracket corner. Numbering follows the bracket's visual
    # layout: team1 & team3 are the left side (semi1's two teams), team2 &
    # team4 are the right side (semi2's two teams). Each is 1 finalist id
    # (1v1) or 2 (2v2) — null for an open slot. All four corners must use
    # the same format.
    team1_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])
    team2_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])
    team3_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])
    team4_player_ids: list[Optional[str]] = Field(default_factory=lambda: [None, None])

    @field_validator("team1_player_ids", "team2_player_ids", "team3_player_ids", "team4_player_ids")
    @classmethod
    def _one_or_two_slots(cls, value: list[Optional[str]]) -> list[Optional[str]]:
        if len(value) not in (1, 2):
            raise ValueError("each bracket team needs 1 player slot (1v1) or 2 (2v2) — use null for an open slot")
        return value

    @model_validator(mode="after")
    def _no_player_on_two_teams(self) -> "SetBracketTeamsRequest":
        sizes = {
            len(self.team1_player_ids),
            len(self.team2_player_ids),
            len(self.team3_player_ids),
            len(self.team4_player_ids),
        }
        if len(sizes) != 1:
            raise ValueError("all four bracket teams must use the same format (all 1v1 or all 2v2)")
        all_ids = (
            self.team1_player_ids + self.team2_player_ids + self.team3_player_ids + self.team4_player_ids
        )
        filled = [uid for uid in all_ids if uid]
        if len(set(filled)) != len(filled):
            raise ValueError("a finalist can only be assigned to one bracket team")
        return self


class DiceTournament(BaseModel):
    id: str
    name: str
    starts_at: datetime
    description: Optional[str] = None
    created_by: str
    created_at: datetime
    hosts: list[TournamentPlayer]
    enrolled_players: list[TournamentPlayer]
    scheduled_matches: list[ScheduledMatch] = Field(default_factory=list)
    completed_games: list[DiceGame] = Field(default_factory=list)
    finalists: list[TournamentPlayer] = Field(default_factory=list)
    bracket: Bracket
