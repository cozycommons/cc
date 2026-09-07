"""Command translation and service-role orchestration for Dice live matches."""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from supabase import Client

from dice.live_projector import effective_event_roots, project_dice_live
from dice.live_types import DiceLiveError, DiceLiveErrorCode as Code, SavedMatch, SavedRules
from dice.prediction_model import ACCEPTED_MODEL, predict_features
from dice.rating_config import CANONICAL_RATING_VERSION
from dice.rating_consistency import validate_canonical_rating_snapshot

CommandKind = Literal[
    "record_throw", "change_throw", "remove_mistake", "retoss", "fix_score",
    "finish", "off_roof", "reopen", "undo_last"
]
Outcome = Literal["miss", "caught", "point", "sink", "self_sink", "fifa", "invalid"]
Coverage = Literal["complete", "partial", "unknown"]
Reason = Literal["target_reached", "forfeit", "time_limit", "mutual_end", "other"]


class LiveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: CommandKind
    client_command_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    match_elapsed_ms: int = Field(default=0, ge=0)
    thrower_id: str | None = None
    outcome: Outcome | None = None
    characteristics: list[Literal["short", "low"]] | None = None
    fifa: dict[str, Any] | None = None
    replay_of: Any | None = None
    target_event_id: str | None = None
    reason: Literal["mistaken_entry", "changed_ruling", "other"] | None = None
    decision_basis: Literal["teams_agreed", "designated_referee", "house_rule", "courtesy", "other"] | None = None
    disputed_calls: list[str] | None = None
    score: list[int] | None = None
    coverage: Coverage | None = None
    termination_reason: Reason | None = None
    responsible_player_id: str | None = None

    @model_validator(mode="after")
    def required_fields(self) -> "LiveCommand":
        common = {"kind", "client_command_id", "expected_version", "match_elapsed_ms"}
        allowed = {
            "record_throw": {"thrower_id", "outcome", "characteristics", "fifa", "replay_of"},
            "change_throw": {"target_event_id", "thrower_id", "outcome", "characteristics", "fifa", "reason", "decision_basis", "disputed_calls"},
            "remove_mistake": {"target_event_id", "reason"},
            "retoss": {"target_event_id", "thrower_id", "decision_basis", "disputed_calls", "characteristics"},
            "fix_score": {"score", "coverage"},
            "finish": {"coverage", "termination_reason"},
            "off_roof": {"responsible_player_id"},
            "reopen": {"target_event_id", "reason"},
            "undo_last": {"target_event_id", "reason"},
        }[self.kind]
        irrelevant = sorted(self.model_fields_set - common - allowed)
        if irrelevant:
            raise ValueError(f"field '{irrelevant[0]}' is not allowed for {self.kind}")
        if self.kind == "record_throw" and self.replay_of is not None and not isinstance(self.replay_of, str):
            raise DiceLiveError(Code.INVALID_REPLAY, "replay_of must be a string event ID")
        required = {
            "record_throw": ("thrower_id", "outcome"), "change_throw": ("target_event_id", "thrower_id", "outcome"),
            "remove_mistake": ("target_event_id",), "retoss": ("thrower_id",),
            "fix_score": ("score", "coverage"), "finish": ("coverage", "termination_reason"),
            "off_roof": ("responsible_player_id",), "reopen": (), "undo_last": (),
        }[self.kind]
        if any(getattr(self, field) is None for field in required):
            raise ValueError(f"{self.kind} requires {', '.join(required)}")
        if self.kind == "record_throw" and self.outcome == "invalid" and not self.characteristics:
            raise ValueError("invalid throws require characteristics")
        if self.kind == "retoss" and self.decision_basis is None:
            raise ValueError("retoss requires decision_basis")
        return self


def _row(client: Client, match_id: str) -> dict[str, Any]:
    rows = client.table("dice_live_matches").select("*").eq("id", match_id).limit(1).execute().data or []
    if not rows:
        raise DiceLiveError(Code.INVALID_MATCH, "live match was not found")
    return rows[0]


def _events(client: Client, match_id: str) -> list[dict[str, Any]]:
    rows = client.table("dice_live_events").select("event").eq("match_id", match_id).order("sequence").execute().data or []
    events = [row["event"] for row in rows]
    for event in events:
        if isinstance(event.get("recorded_at"), str):
            event["recorded_at"] = datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00"))
    return events


def _match(row: dict[str, Any]) -> SavedMatch:
    return SavedMatch(match_id=str(row["id"]), team_order=row["team_order"], teams=row["teams"])


def _team(row: dict[str, Any], player_id: str) -> str:
    for team, players in row["teams"].items():
        if player_id in players:
            return team
    raise DiceLiveError(Code.INVALID_OBSERVATION, "player is not in the saved roster")


def _delta(
    row: dict[str, Any],
    player_id: str,
    outcome: str,
    fifa: dict[str, Any] | None = None,
) -> list[int]:
    points = {"miss": 0, "caught": 0, "point": 1, "sink": 1, "self_sink": 2, "fifa": 1, "invalid": 0}
    if outcome == "fifa" and fifa and fifa.get("finish") == "goal_saved":
        return [0, 0]
    scoring = next(team for team in row["team_order"] if team != _team(row, player_id)) if outcome in {"self_sink", "fifa"} else _team(row, player_id)
    return [points[outcome] if team == scoring else 0 for team in row["team_order"]]


def _envelope(command: LiveCommand, match_id: str, user_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "match_id": match_id, "match_version": command.expected_version + 1,
            "sequence": 1, "client_command_id": command.client_command_id, "command_index": 0,
            "recorded_by": user_id, "recorded_at": datetime.now(timezone.utc),
            "match_elapsed_ms": command.match_elapsed_ms, "kind": kind, **fields}


def _validate_replay_target(events: list[dict[str, Any]], target_id: str) -> str:
    if not target_id.strip():
        raise DiceLiveError(Code.INVALID_REPLAY, "replay_of must reference a non-empty event ID", event_id=target_id)
    target = next((event for event in events if event.get("id") == target_id), None)
    if target is None:
        raise DiceLiveError(Code.INVALID_REPLAY, "replay_of target is not in this match prefix", event_id=target_id)
    if target.get("kind") != "retoss_decision":
        raise DiceLiveError(Code.INVALID_REPLAY, "replay_of target must be a retoss_decision", event_id=target_id,
                            sequence=target.get("sequence"))
    effective_roots = effective_event_roots(events)
    if not any(root["id"] == target_id for root, _ in effective_roots):
        raise DiceLiveError(Code.INVALID_REPLAY, "replay_of target is inactive", event_id=target_id,
                            sequence=target.get("sequence"))
    if any(
        root.get("replay_of") == target_id or active.get("replay_resolution_for") == target_id
        for root, active in effective_roots
    ):
        raise DiceLiveError(Code.INVALID_REPLAY, "replay_of target is already fulfilled", event_id=target_id,
                            sequence=target.get("sequence"))
    return target_id


def _translate_command(row: dict[str, Any], events: list[dict[str, Any]], command: LiveCommand, user_id: str) -> list[dict[str, Any]]:
    kind = command.kind
    if kind in {"undo_last", "remove_mistake", "reopen"}:
        target = command.target_event_id or next((event["id"] for event in reversed(events) if event["kind"] not in {"correction", "retoss_decision"}), None)
        if target is None:
            raise DiceLiveError(Code.INVALID_CORRECTION, "no event is available to correct")
        correction = _envelope(command, str(row["id"]), user_id, "correction", target_event_id=target,
                               reason=command.reason or "mistaken_entry")
        if kind == "reopen":
            target_event = next((event for event in events if event["id"] == target), None)
            if target_event and target_event["kind"] == "completion":
                replacement = _envelope(command, str(row["id"]), user_id, "score_checkpoint",
                    score=row["score"], coverage="partial",
                    coverage_after=target_event.get("coverage_after"), replacement_for=target)
                replacement["command_index"] = 1
                return [correction, replacement]
        return [correction]
    if kind == "record_throw" or kind == "change_throw":
        replay_of = _validate_replay_target(events, command.replay_of) if kind == "record_throw" and command.replay_of is not None else None
        event = _envelope(command, str(row["id"]), user_id, "observation", thrower_id=command.thrower_id,
            throwing_team_id=_team(row, command.thrower_id), outcome=command.outcome,
            score_delta=_delta(row, command.thrower_id, command.outcome, command.fifa), characteristics=command.characteristics,
            fifa=command.fifa, replacement_for=command.target_event_id if kind == "change_throw" else None,
            replay_of=replay_of)
        if kind == "change_throw":
            correction = _envelope(command, str(row["id"]), user_id, "correction", target_event_id=command.target_event_id,
                                   reason=command.reason or "mistaken_entry", disputed_calls=command.disputed_calls,
                                   decision_basis=command.decision_basis)
            event["command_index"] = 1
            return [correction, event]
        return [event]
    if kind == "retoss":
        target = command.target_event_id
        target_event = next((event for event in events if event["id"] == target), None) if target else None
        thrower = target_event["thrower_id"] if target_event else command.thrower_id
        return [_envelope(command, str(row["id"]), user_id, "retoss_decision", thrower_id=thrower,
            throwing_team_id=_team(row, thrower), decision_basis=command.decision_basis,
            disputed_calls=command.disputed_calls or [], characteristics=command.characteristics, target_event_id=target)]
    if kind == "off_roof":
        return [_envelope(command, str(row["id"]), user_id, "off_roof", responsible_player_id=command.responsible_player_id,
                          losing_team_id=_team(row, command.responsible_player_id), replacement_for=None)]
    score = command.score if kind == "fix_score" else row["score"]
    coverage = command.coverage
    previous = next(
        (
            root["id"]
            for root, active in reversed(effective_event_roots(events))
            if active["kind"] in {"score_checkpoint", "completion"}
        ),
        None,
    )
    if kind == "fix_score":
        return [_envelope(command, str(row["id"]), user_id, "score_checkpoint", score=score, coverage=coverage,
                          coverage_after=previous, replacement_for=None, replay_resolution_for=None, replay_disposition=None)]
    return [_envelope(command, str(row["id"]), user_id, "completion", score=score, coverage=coverage,
        coverage_after=previous, replacement_for=None, replay_resolution_for=None, replay_disposition=None,
        termination_reason=command.termination_reason)]


def translate_command(row: dict[str, Any], events: list[dict[str, Any]], command: LiveCommand, user_id: str) -> list[dict[str, Any]]:
    translated = _translate_command(row, events, command, user_id)
    for index, event in enumerate(translated):
        event["sequence"] = len(events) + index + 1
        event["match_version"] = command.expected_version + 1
    return translated


def append_command(client: Client, match_id: str, user_id: str, command: LiveCommand) -> dict[str, Any]:
    canonical_payload = command.model_dump(mode="json")
    prior = (client.table("dice_live_commands").select("canonical_payload,receipt")
             .eq("match_id", match_id).eq("recorded_by", user_id)
             .eq("client_command_id", command.client_command_id).limit(1).execute().data or [])
    if prior:
        if prior[0]["canonical_payload"] == canonical_payload:
            return prior[0]["receipt"]
        raise RuntimeError("dice_live.command_id_conflict")
    row, events = _row(client, match_id), _events(client, match_id)
    candidate = translate_command(row, events, command, user_id)
    projection = project_dice_live(_match(row), row["rules_snapshot"], [*events, *candidate]).model_dump(mode="json")
    persisted_events = json.loads(json.dumps(candidate, default=lambda value: value.isoformat() if isinstance(value, datetime) else value))
    response = client.rpc("dice_live_append_command", {
        "p_match_id": match_id, "p_recorded_by": user_id, "p_client_command_id": command.client_command_id,
        "p_expected_version": command.expected_version, "p_canonical_payload": canonical_payload,
        "p_events": persisted_events, "p_projection": projection, "p_score": projection["score"],
        "p_status": projection["status"], "p_detail_coverage": projection["coverage"],
    }).execute().data
    clear_cache = getattr(client, "clear_cache", None)
    if callable(clear_cache):
        clear_cache()
    receipt = response[0] if isinstance(response, list) else response
    if receipt.get("official_result") is None:
        from dice.repository import get_live_result
        materialized = get_live_result(client, match_id)
        if materialized:
            receipt["official_result"] = materialized
    return receipt


def _validated_prediction_profiles(client: Client) -> list[dict[str, Any]]:
    """Read one coherent rating generation or fail before match creation."""

    snapshot = client.rpc("dice_rating_analytics_snapshot").execute().data or {}
    if snapshot.get("snapshot_version") != "dice-rating-analytics/v1":
        raise DiceLiveError(Code.INVALID_STATE, "rating snapshot is unavailable")
    try:
        validate_canonical_rating_snapshot(
            snapshot.get("profiles") or [], snapshot.get("games") or [], snapshot.get("players") or []
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DiceLiveError(Code.INVALID_STATE, "canonical rating snapshot is inconsistent") from exc
    return snapshot["profiles"]


def create_live_match(client: Client, user_id: str, team_order: list[str], teams: dict[str, list[str]], rules: dict[str, Any]) -> dict[str, Any]:
    try:
        SavedRules.model_validate(rules)
    except ValidationError as exc:
        raise DiceLiveError(
            Code.INVALID_RULES,
            f"saved rules are invalid: {exc.errors()[0]['msg']}",
        ) from None
    roster_ids = [player_id for team in team_order for player_id in teams[team]]
    profiles = [row for row in _validated_prediction_profiles(client) if row["user_id"] in roster_ids]
    existing_ids = {row["user_id"] for row in profiles}
    missing_ids = [player_id for player_id in roster_ids if player_id not in existing_ids]
    if missing_ids:
        raise DiceLiveError(
            Code.INVALID_ROSTER,
            "all live-match roster members must have registered profiles",
        )
    ratings = {row["user_id"]: row.get("elo_rating", 1500) for row in profiles}
    rating_snapshot = {
        team_id: [{"user_id": player_id, "rating": ratings[player_id],
                   "system_version": CANONICAL_RATING_VERSION}
                  for player_id in teams[team_id]]
        for team_id in team_order
    }
    profile_by_id = {row["user_id"]: row for row in profiles}
    team_prior_rates = {
        team_id: sum(
            (profile_by_id[player_id].get("ranked_wins", 0) + 1)
            / (profile_by_id[player_id].get("ranked_games_played", 0) + 2)
            for player_id in teams[team_id]
        ) / len(teams[team_id])
        for team_id in team_order
    }
    captured_at = datetime.now(timezone.utc).isoformat()
    rate_difference = team_prior_rates[team_order[0]] - team_prior_rates[team_order[1]]
    prediction_snapshot = {
        "model_id": ACCEPTED_MODEL.model_id,
        "model_version": ACCEPTED_MODEL.model_version,
        "dataset_version": ACCEPTED_MODEL.dataset_version,
        "captured_at": captured_at,
        "team1_prior_win_rate": team_prior_rates[team_order[0]],
        "team2_prior_win_rate": team_prior_rates[team_order[1]],
        "team1_probability": predict_features(ACCEPTED_MODEL, rate_difference),
    }
    row = client.table("dice_live_matches").insert({"created_by": user_id, "team_order": team_order, "teams": teams,
        "rules_snapshot": rules, "rating_snapshot": rating_snapshot,
        "prediction_snapshot": prediction_snapshot}).execute().data[0]
    client.table("dice_live_referees").insert({"match_id": row["id"], "user_id": user_id}).execute()
    return row


def set_membership(client: Client, match_id: str, user_id: str, joined: bool) -> dict[str, Any]:
    existing = client.table("dice_live_referees").select("*").eq("match_id", match_id).eq("user_id", user_id).limit(1).execute().data or []
    if joined:
        payload = {"match_id": match_id, "user_id": user_id, "left_at": None}
        return client.table("dice_live_referees").upsert(payload, on_conflict="match_id,user_id").execute().data[0]
    if not existing:
        return {"match_id": match_id, "user_id": user_id, "left_at": None}
    return client.table("dice_live_referees").update({"left_at": datetime.now(timezone.utc).isoformat()}).eq("match_id", match_id).eq("user_id", user_id).execute().data[0]
