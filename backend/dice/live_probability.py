"""Pure live win-probability projection for Dice games.

This module is intentionally independent of Supabase, HTTP, and feature flags.
The live referee projection remains the source of truth for score and status;
this function only derives a displayable estimate from that snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dice.live_projector import project_dice_live
from dice.live_types import DiceLiveError, DiceLiveErrorCode, DiceLiveProjection, SavedRules

_EPSILON = 1e-9
MODEL_ID = "elo-score-composition"
MODEL_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class LiveProbabilityInput:
    """Immutable, server-derived inputs for one prediction."""

    match_version: int
    team1_score: int
    team2_score: int
    target_score: int
    win_by: int
    pregame_team1_probability: float


@dataclass(frozen=True, slots=True)
class LiveProbability:
    match_version: int
    team1: float
    team2: float
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION


@dataclass(frozen=True, slots=True)
class LiveProbabilityPoint:
    """One command boundary in the probability story shown to players."""

    match_version: int
    score: tuple[int, int]
    team1: float
    team2: float
    swing: float
    kind: str
    outcome: str | None = None
    thrower_id: str | None = None
    fifa_finish: str | None = None
    fifa_actor_id: str | None = None


def project_live_probability(inputs: LiveProbabilityInput) -> LiveProbability:
    """Project the chance each team wins from a validated score snapshot.

    Raises a stable ``DiceLiveError`` for malformed or non-finite inputs. The
    caller may treat this as an unavailable optional adornment; it must not
    block recording a throw or finishing a game.
    """

    _validate(inputs)
    point_probability = _calibrate_point_probability(
        inputs.pregame_team1_probability, inputs.target_score, inputs.win_by
    )
    team1 = _game_probability(
        point_probability,
        inputs.team1_score,
        inputs.team2_score,
        inputs.target_score,
        inputs.win_by,
    )
    return LiveProbability(
        match_version=inputs.match_version,
        team1=team1,
        team2=1.0 - team1,
    )


def project_live_projection(
    projection: DiceLiveProjection,
    rules: SavedRules,
    *,
    match_version: int,
    pregame_team1_probability: float,
) -> LiveProbability:
    """Adapt the authoritative live projection without reinterpreting events."""

    if projection.status == "completed":
        if projection.score[0] == projection.score[1]:
            _invalid("completed game must have a winning team")
        team1 = 1.0 if projection.score[0] > projection.score[1] else 0.0
        return LiveProbability(
            match_version=match_version,
            team1=team1,
            team2=1.0 - team1,
        )

    return project_live_probability(
        LiveProbabilityInput(
            match_version=match_version,
            team1_score=projection.score[0],
            team2_score=projection.score[1],
            target_score=rules.target_score,
            win_by=rules.win_by,
            pregame_team1_probability=pregame_team1_probability,
        )
    )


def project_live_history(
    match: Mapping[str, Any],
    rules: SavedRules | Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    pregame_team1_probability: float,
) -> tuple[LiveProbabilityPoint, ...]:
    """Rebuild the display timeline from canonical command boundaries.

    Corrections remain visible as later moments while each point is projected
    from the authoritative prefix. The corrected throw is therefore never
    double-counted in the score used for the new probability.
    """

    parsed_rules = rules if isinstance(rules, SavedRules) else SavedRules.model_validate(rules)
    if not 0.0 <= pregame_team1_probability <= 1.0:
        _invalid("pregame probability must be between 0 and 1")

    points = [LiveProbabilityPoint(
        match_version=0,
        score=(0, 0),
        team1=pregame_team1_probability,
        team2=1.0 - pregame_team1_probability,
        swing=0.0,
        kind="start",
    )]
    ordered = sorted(events, key=lambda event: event["sequence"])
    by_id = {event["id"]: event for event in ordered}
    versions = sorted({int(event["match_version"]) for event in ordered})
    previous = pregame_team1_probability
    for version in versions:
        prefix = [event for event in ordered if int(event["match_version"]) <= version]
        command_events = [event for event in ordered if int(event["match_version"]) == version]
        projection = project_dice_live(match, parsed_rules, prefix)
        probability = project_live_projection(
            projection,
            parsed_rules,
            match_version=version,
            pregame_team1_probability=pregame_team1_probability,
        )
        last = command_events[-1]
        first = command_events[0]
        correction_target = by_id.get(first.get("target_event_id")) if first["kind"] == "correction" else None
        kind = (
            "reopen" if correction_target
            and correction_target["kind"] in {"completion", "off_roof"}
            and last["kind"] not in {"completion", "off_roof"}
            else "correction" if first["kind"] == "correction"
            else "finish" if last["kind"] in {"completion", "off_roof"}
            else "score_update" if last["kind"] == "score_checkpoint"
            else "retoss" if last["kind"] == "retoss_decision"
            else "play"
        )
        observation = next(
            (event for event in reversed(command_events) if event["kind"] == "observation"),
            None,
        )
        fifa = observation.get("fifa") if observation and observation.get("outcome") == "fifa" else None
        fifa_finish = fifa.get("finish") if fifa else None
        fifa_actor_id = (
            fifa.get("saver_id") if fifa_finish == "goal_saved"
            else fifa.get("catcher_id") if fifa_finish == "kick_catch"
            else fifa.get("kicker_id") if fifa_finish == "goal"
            else None
        )
        points.append(LiveProbabilityPoint(
            match_version=version,
            score=(projection.score[0], projection.score[1]),
            team1=probability.team1,
            team2=probability.team2,
            swing=probability.team1 - previous,
            kind=kind,
            outcome=observation.get("outcome") if observation else None,
            thrower_id=observation.get("thrower_id") if observation else last.get("thrower_id"),
            fifa_finish=fifa_finish,
            fifa_actor_id=fifa_actor_id,
        ))
        previous = probability.team1
    return tuple(points)


def _validate(value: LiveProbabilityInput) -> None:
    if value.match_version <= 0:
        _invalid("match_version must be positive")
    if value.team1_score < 0 or value.team2_score < 0:
        _invalid("scores must be non-negative")
    if value.target_score <= 0 or value.win_by <= 0:
        _invalid("target_score and win_by must be positive")
    if not 0.0 <= value.pregame_team1_probability <= 1.0:
        _invalid("pregame probability must be between 0 and 1")
    if value.team1_score >= value.target_score and value.team2_score >= value.target_score:
        if abs(value.team1_score - value.team2_score) < value.win_by:
            _invalid("score cannot have both teams past target without a winner")


def _invalid(message: str) -> None:
    raise DiceLiveError(DiceLiveErrorCode.INVALID_STATE, message)


def _won(score: int, opponent: int, target: int, win_by: int) -> bool:
    return score >= target and score - opponent >= win_by


def _game_probability(point: float, team1: int, team2: int, target: int, win_by: int) -> float:
    if _won(team1, team2, target, win_by):
        return 1.0
    if _won(team2, team1, target, win_by):
        return 0.0
    # Once both teams are at/above target, only the win-by race remains.
    if team1 >= target - 1 and team2 >= target - 1:
        difference = team1 - team2
        if abs(point - 0.5) < _EPSILON:
            return (difference + win_by) / (2 * win_by)
        ratio = (1.0 - point) / point
        position = difference + win_by
        span = 2 * win_by
        return (1.0 - ratio**position) / (1.0 - ratio**span)
    memo: dict[tuple[int, int], float] = {}

    def solve(left: int, right: int) -> float:
        if _won(left, right, target, win_by):
            return 1.0
        if _won(right, left, target, win_by):
            return 0.0
        if left >= target - 1 and right >= target - 1:
            difference = left - right
            if abs(point - 0.5) < _EPSILON:
                return (difference + win_by) / (2 * win_by)
            ratio = (1.0 - point) / point
            position = difference + win_by
            span = 2 * win_by
            return (1.0 - ratio**position) / (1.0 - ratio**span)
        key = (left, right)
        if key not in memo:
            memo[key] = point * solve(left + 1, right) + (1 - point) * solve(left, right + 1)
        return memo[key]

    return solve(team1, team2)


def _calibrate_point_probability(pregame: float, target: int, win_by: int) -> float:
    if pregame <= 0.0:
        return _EPSILON
    if pregame >= 1.0:
        return 1.0 - _EPSILON
    low, high = _EPSILON, 1.0 - _EPSILON
    for _ in range(60):
        midpoint = (low + high) / 2
        if _game_probability(midpoint, 0, 0, target, win_by) < pregame:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2
