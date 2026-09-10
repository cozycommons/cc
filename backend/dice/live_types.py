"""Strict persistence-independent types for the Dice live-event domain."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter


class DiceLiveErrorCode(StrEnum):
    INVALID_MATCH = "dice_live.invalid_match"
    INVALID_ROSTER = "dice_live.invalid_roster"
    INVALID_RULES = "dice_live.invalid_rules"
    INVALID_EVENT_SCHEMA = "dice_live.invalid_event_schema"
    INVALID_SEQUENCE = "dice_live.invalid_sequence"
    INVALID_COMMAND = "dice_live.invalid_command"
    INVALID_OBSERVATION = "dice_live.invalid_observation"
    INVALID_CORRECTION = "dice_live.invalid_correction"
    INVALID_REPLAY = "dice_live.invalid_replay"
    INVALID_COVERAGE = "dice_live.invalid_coverage"
    INVALID_COMPLETION = "dice_live.invalid_completion"
    INVALID_STATE = "dice_live.invalid_state"


class DiceLiveError(Exception):
    """A stable domain failure safe to expose across persistence/API boundaries."""

    def __init__(
        self,
        code: DiceLiveErrorCode,
        message: str,
        *,
        event_id: str | None = None,
        sequence: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.event_id = event_id
        self.sequence = sequence
        context = ", ".join(
            item
            for item in (
                f"event_id={event_id}" if event_id is not None else "",
                f"sequence={sequence}" if sequence is not None else "",
            )
            if item
        )
        super().__init__(f"{code}: {message}" + (f" ({context})" if context else ""))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SavedMatch(StrictModel):
    match_id: str = Field(min_length=1)
    team_order: list[str] = Field(min_length=2, max_length=2)
    teams: dict[str, list[str]]


class CallPolicy(StrictModel):
    low_call_deadline: Literal["before_surface_contact"]
    low_call_exceptions: list[str] = Field(max_length=0)
    short_boundary: Literal["center_line_is_short"]
    midline_remedy: Literal["consume_attempt"]
    dispute_authority: Literal["teams_or_designated_referee"]
    uncertain_call_remedy: Literal["retoss"]


class SavedRules(StrictModel):
    contract_version: Literal[1]
    ruleset_version: Literal[1]
    scoring_version: Literal[1]
    target_score: int = Field(gt=0)
    win_by: int = Field(gt=0)
    call_policy: CallPolicy


DecisionBasis = Literal[
    "teams_agreed", "designated_referee", "house_rule", "courtesy", "other"
]
DisputedCall = Literal[
    "short",
    "low",
    "catch",
    "trap",
    "interference",
    "not_ready",
    "equipment",
    "other",
]
InvalidCharacteristic = Literal["short", "low"]
Outcome = Literal["miss", "caught", "point", "sink", "self_sink", "fifa", "invalid"]
Score = list[int]
StatCount = Annotated[int, Field(ge=0)]


class DiceLiveOutcomeCounts(StrictModel):
    miss: StatCount = 0
    caught: StatCount = 0
    point: StatCount = 0
    sink: StatCount = 0
    self_sink: StatCount = 0
    fifa: StatCount = 0
    invalid: StatCount = 0


class DiceLivePlayerStats(StrictModel):
    outcomes: DiceLiveOutcomeCounts = Field(default_factory=DiceLiveOutcomeCounts)
    table_catches: StatCount = 0
    fifa_goals: StatCount = 0
    fifa_kicks: StatCount = 0
    fifa_catches: StatCount = 0
    fifa_saves: StatCount = 0


class EventEnvelope(StrictModel):
    id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    match_version: int = Field(gt=0)
    sequence: int = Field(gt=0)
    client_command_id: str = Field(min_length=1)
    command_index: int = Field(ge=0)
    recorded_by: str = Field(min_length=1)
    recorded_at: AwareDatetime
    match_elapsed_ms: int = Field(ge=0)


class ObservationEvent(EventEnvelope):
    kind: Literal["observation"]
    thrower_id: str = Field(min_length=1)
    throwing_team_id: str = Field(min_length=1)
    outcome: Outcome
    score_delta: Score = Field(min_length=2, max_length=2)
    catcher_id: str | None = None
    characteristics: list[InvalidCharacteristic] | None = None
    fifa: FifaPlay | None = None
    replacement_for: str | None = None
    replay_of: str | None = None


class FifaPlay(StrictModel):
    finish: Literal["kick_catch", "goal", "goal_saved"]
    kicker_id: str = Field(min_length=1)
    catcher_id: str | None = None
    saver_id: str | None = None


class CorrectionEvent(EventEnvelope):
    kind: Literal["correction"]
    target_event_id: str = Field(min_length=1)
    reason: Literal["mistaken_entry", "changed_ruling", "other"]
    disputed_calls: list[DisputedCall] | None = None
    decision_basis: DecisionBasis | None = None


class RetossDecisionEvent(EventEnvelope):
    kind: Literal["retoss_decision"]
    thrower_id: str = Field(min_length=1)
    throwing_team_id: str = Field(min_length=1)
    decision_basis: DecisionBasis
    disputed_calls: list[DisputedCall] = Field(default_factory=list)
    characteristics: list[InvalidCharacteristic] | None = None
    target_event_id: str | None = None


class OffRoofEvent(EventEnvelope):
    kind: Literal["off_roof"]
    responsible_player_id: str = Field(min_length=1)
    losing_team_id: str = Field(min_length=1)
    replacement_for: str | None = None


class BoundaryEvent(EventEnvelope):
    score: Score = Field(min_length=2, max_length=2)
    coverage: Literal["complete", "partial", "unknown"]
    coverage_after: str | None
    replacement_for: str | None = None
    replay_resolution_for: str | None = None
    replay_disposition: Literal["unobserved", "cancelled"] | None = None


class ScoreCheckpointEvent(BoundaryEvent):
    kind: Literal["score_checkpoint"]


class CompletionEvent(BoundaryEvent):
    kind: Literal["completion"]
    termination_reason: Literal[
        "target_reached", "forfeit", "time_limit", "mutual_end", "other"
    ]


DiceLiveEvent = Annotated[
    ObservationEvent
    | CorrectionEvent
    | RetossDecisionEvent
    | OffRoofEvent
    | ScoreCheckpointEvent
    | CompletionEvent,
    Field(discriminator="kind"),
]
DICE_LIVE_EVENT_ADAPTER = TypeAdapter(DiceLiveEvent)


class DiceLiveProjection(StrictModel):
    score: Score = Field(min_length=2, max_length=2)
    status: Literal["active", "awaiting_replay", "ready_to_finish", "completed"]
    termination_reason: Literal[
        "target_reached", "off_roof", "forfeit", "time_limit", "mutual_end", "other"
    ] | None = None
    coverage: Literal["complete", "partial", "unknown"]
    observations: int = Field(ge=0)
    stats: dict[Outcome, StatCount]
    player_stats: dict[str, DiceLivePlayerStats] = Field(default_factory=dict)
