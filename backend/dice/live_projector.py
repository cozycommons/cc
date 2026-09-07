"""Pure deterministic projection for strict Dice live-event logs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from dice.live_types import (
    DICE_LIVE_EVENT_ADAPTER,
    DiceLiveError,
    DiceLiveErrorCode as Code,
    DiceLiveEvent,
    DiceLiveOutcomeCounts,
    DiceLivePlayerStats,
    DiceLiveProjection,
    EventEnvelope,
    SavedMatch,
    SavedRules,
)

Event = dict[str, Any]


def effective_event_roots(events: Sequence[Event]) -> list[tuple[Event, Event]]:
    corrections = {
        event["target_event_id"]: event
        for event in events
        if event.get("kind") == "correction"
    }
    replacements = {
        event["replacement_for"]: event
        for event in events
        if event.get("replacement_for") is not None
    }

    def effective(event: Event) -> Event | None:
        if event["id"] not in corrections:
            return event
        replacement = replacements.get(event["id"])
        return effective(replacement) if replacement else None

    roots = [
        event
        for event in events
        if event.get("kind") != "correction"
        and event.get("replacement_for") is None
    ]
    return [(root, active) for root in roots if (active := effective(root)) is not None]


def _duplicate_event(events: Sequence[Event], field: str) -> Event | None:
    seen: set[Any] = set()
    for event in events:
        value = event.get(field)
        if value in seen:
            return event
        seen.add(value)
    return None


def _error(
    code: Code, message: str, event: Mapping[str, Any] | None = None
) -> DiceLiveError:
    return DiceLiveError(
        code,
        message,
        event_id=event.get("id") if event else None,
        sequence=event.get("sequence") if event else None,
    )


def _require(
    condition: bool,
    code: Code,
    message: str,
    event: Mapping[str, Any] | None = None,
) -> None:
    if not condition:
        raise _error(code, message, event)


def _validated_inputs(
    match: SavedMatch | Mapping[str, Any],
    rules: SavedRules | Mapping[str, Any],
    events: Sequence[DiceLiveEvent | Mapping[str, Any]],
) -> tuple[Event, Event, list[Event]]:
    try:
        parsed_match = (
            match if isinstance(match, SavedMatch) else SavedMatch.model_validate(match)
        )
    except ValidationError as exc:
        raise _error(Code.INVALID_MATCH, f"saved match is invalid: {exc.errors()[0]['msg']}") from None
    try:
        parsed_rules = (
            rules if isinstance(rules, SavedRules) else SavedRules.model_validate(rules)
        )
    except ValidationError as exc:
        raise _error(Code.INVALID_RULES, f"saved rules are invalid: {exc.errors()[0]['msg']}") from None

    parsed_events: list[Event] = []
    for raw in events:
        context = (
            raw.model_dump(mode="python")
            if isinstance(raw, EventEnvelope)
            else raw
            if isinstance(raw, Mapping)
            else None
        )
        try:
            # Supabase JSONB returns timestamps as ISO strings. Strict event
            # validation still applies, but JSON transport values must enter
            # through Pydantic's JSON path so an aware timestamp is decoded.
            parsed = (
                DICE_LIVE_EVENT_ADAPTER.validate_json(json.dumps(raw))
                if isinstance(raw, Mapping) and isinstance(raw.get("recorded_at"), str)
                else DICE_LIVE_EVENT_ADAPTER.validate_python(raw)
            )
        except ValidationError as exc:
            detail = exc.errors()[0]
            raise _error(
                Code.INVALID_EVENT_SCHEMA,
                f"event schema is invalid at {'.'.join(map(str, detail['loc']))}: {detail['msg']}",
                context,
            ) from None
        parsed_events.append(parsed.model_dump(mode="python"))
    return (
        parsed_match.model_dump(mode="python"),
        parsed_rules.model_dump(mode="python"),
        parsed_events,
    )


def project_dice_live(
    match: SavedMatch | Mapping[str, Any],
    rules: SavedRules | Mapping[str, Any],
    events: Sequence[DiceLiveEvent | Mapping[str, Any]],
) -> DiceLiveProjection:
    """Validate and project a complete log without persistence or side effects."""

    saved_match, saved_rules, parsed_events = _validated_inputs(match, rules, events)
    return _project(saved_match, saved_rules, parsed_events, validate_prefixes=True)


def _project(
    match: Event, rules: Event, events: list[Event], *, validate_prefixes: bool
) -> DiceLiveProjection:
    ordered = sorted(events, key=lambda event: event["sequence"])
    ids = [event["id"] for event in ordered]
    _require(
        len(set(ids)) == len(ids),
        Code.INVALID_SEQUENCE,
        "event IDs must be unique",
        _duplicate_event(ordered, "id"),
    )
    _require(
        [event["sequence"] for event in ordered] == list(range(1, len(ordered) + 1)),
        Code.INVALID_SEQUENCE,
        "event sequences must be unique and contiguous from one",
        next(
            (
                event
                for expected, event in enumerate(ordered, start=1)
                if event["sequence"] != expected
            ),
            None,
        ),
    )
    _require(
        all(event["match_id"] == match["match_id"] for event in ordered),
        Code.INVALID_SEQUENCE,
        "all events must belong to the saved match",
        next(
            (event for event in ordered if event["match_id"] != match["match_id"]),
            None,
        ),
    )

    team_order = match["team_order"]
    teams = match["teams"]
    _require(
        len(set(team_order)) == 2 and set(team_order) == set(teams),
        Code.INVALID_MATCH,
        "saved match must define exactly the two ordered teams",
    )
    roster = [player for team in team_order for player in teams[team]]
    _require(
        len(roster) == len(set(roster)) and all(teams[team] for team in team_order),
        Code.INVALID_MATCH,
        "players must be unique and each team must be nonempty",
    )
    player_team = {
        player_id: team_id
        for team_id, player_ids in teams.items()
        for player_id in player_ids
    }

    def command_key(event: Event) -> tuple[str, str, str]:
        return event["match_id"], event["recorded_by"], event["client_command_id"]

    command_groups: dict[tuple[str, str, str], list[Event]] = defaultdict(list)
    for event in ordered:
        command_groups[command_key(event)].append(event)
    for group in command_groups.values():
        group.sort(key=lambda event: event["command_index"])
        first = group[0]
        _require(
            [event["command_index"] for event in group] == list(range(len(group))),
            Code.INVALID_COMMAND,
            "command indexes must be unique and contiguous from zero",
            first,
        )
        _require(
            [event["sequence"] for event in group]
            == list(range(first["sequence"], first["sequence"] + len(group))),
            Code.INVALID_COMMAND,
            "events in a command must occupy contiguous sequences",
            first,
        )
        valid_single = len(group) == 1 and first.get("replacement_for") is None
        valid_pair = (
            len(group) == 2
            and first["kind"] == "correction"
            and group[1].get("replacement_for") == first["target_event_id"]
        )
        _require(
            valid_single or valid_pair,
            Code.INVALID_COMMAND,
            "a command must contain one event or an atomic correction/replacement pair",
            first,
        )

    if validate_prefixes:
        for index in range(len(ordered) - 1):
            if command_key(ordered[index]) != command_key(ordered[index + 1]):
                _project(match, rules, ordered[: index + 1], validate_prefixes=False)

    by_id = {event["id"]: event for event in ordered}
    correction_events = [event for event in ordered if event["kind"] == "correction"]
    all_retoss_decisions = [
        event for event in ordered if event["kind"] == "retoss_decision"
    ]
    replacement_events = [
        event for event in ordered if event.get("replacement_for") is not None
    ]
    corrections = {event["target_event_id"]: event for event in correction_events}
    replacements = {event["replacement_for"]: event for event in replacement_events}
    _require(
        len(corrections) == len(correction_events),
        Code.INVALID_CORRECTION,
        "an event may be directly corrected only once",
        _duplicate_event(correction_events, "target_event_id"),
    )
    _require(
        len(replacements) == len(replacement_events),
        Code.INVALID_CORRECTION,
        "an event may have only one direct replacement",
        _duplicate_event(replacement_events, "replacement_for"),
    )

    def decision_view(cutoff: int) -> tuple[list[Event], dict[str, Event]]:
        decisions = [
            decision
            for decision in all_retoss_decisions
            if decision["sequence"] <= cutoff
            and (
                decision["id"] not in corrections
                or corrections[decision["id"]]["sequence"] > cutoff
            )
        ]
        targeted = [
            decision
            for decision in decisions
            if decision.get("target_event_id") is not None
        ]
        return decisions, {
            decision["target_event_id"]: decision for decision in targeted
        }

    retoss_decisions, retosses_by_target = decision_view(len(ordered))
    targeted_retosses = [
        event for event in retoss_decisions if event.get("target_event_id") is not None
    ]
    _require(
        len(retosses_by_target) == len(targeted_retosses),
        Code.INVALID_REPLAY,
        "an event may be targeted by only one retoss decision",
        _duplicate_event(targeted_retosses, "target_event_id"),
    )

    points = {
        "miss": 0,
        "caught": 0,
        "point": 1,
        "sink": 1,
        "self_sink": 2,
        "fifa": 1,
        "invalid": 0,
    }
    for event in ordered:
        if event["kind"] != "observation":
            continue
        thrower = event["thrower_id"]
        _require(
            thrower in player_team,
            Code.INVALID_OBSERVATION,
            "thrower is not in the saved roster",
            event,
        )
        throwing_team = event["throwing_team_id"]
        _require(
            throwing_team == player_team[thrower],
            Code.INVALID_OBSERVATION,
            "throwing team must be derived from the thrower",
            event,
        )
        characteristics = event.get("characteristics")
        _require(
            (event["outcome"] == "invalid" and bool(characteristics))
            or (event["outcome"] != "invalid" and characteristics is None),
            Code.INVALID_OBSERVATION,
            "short/low characteristics are required only for invalid observations",
            event,
        )
        fifa = event.get("fifa")
        if event["outcome"] == "fifa":
            _require(
                fifa is not None,
                Code.INVALID_OBSERVATION,
                "FIFA observations require participant attribution",
                event,
            )
            kicker = fifa["kicker_id"]
            _require(
                kicker in player_team and player_team[kicker] != throwing_team,
                Code.INVALID_OBSERVATION,
                "FIFA kicker must be on the receiving team",
                event,
            )
            catcher = fifa.get("catcher_id")
            saver = fifa.get("saver_id")
            if fifa["finish"] == "kick_catch":
                _require(
                    catcher in player_team
                    and catcher != kicker
                    and player_team[catcher] == player_team[kicker],
                    Code.INVALID_OBSERVATION,
                    "FIFA kick-catch requires a distinct receiving-team catcher",
                    event,
                )
                _require(
                    saver is None,
                    Code.INVALID_OBSERVATION,
                    "FIFA kick-catch cannot name a saver",
                    event,
                )
            elif fifa["finish"] == "goal":
                _require(
                    catcher is None and saver is None,
                    Code.INVALID_OBSERVATION,
                    "FIFA goal cannot name a catcher or saver",
                    event,
                )
            else:
                _require(
                    catcher is None
                    and saver in player_team
                    and player_team[saver] == throwing_team,
                    Code.INVALID_OBSERVATION,
                    "saved FIFA goal requires a saver on the throwing team",
                    event,
                )
        else:
            _require(
                fifa is None,
                Code.INVALID_OBSERVATION,
                "only FIFA observations may carry FIFA attribution",
                event,
            )
        opponent = next(team for team in team_order if team != throwing_team)
        scoring_team = (
            opponent if event["outcome"] in {"self_sink", "fifa"} else throwing_team
        )
        point_value = (
            0
            if event["outcome"] == "fifa"
            and event["fifa"]["finish"] == "goal_saved"
            else points[event["outcome"]]
        )
        expected_delta = [point_value if team == scoring_team else 0 for team in team_order]
        _require(
            event["score_delta"] == expected_delta,
            Code.INVALID_OBSERVATION,
            f"score delta must be server-derived as {expected_delta}",
            event,
        )

    for event in ordered:
        if event["kind"] != "off_roof":
            continue
        responsible_player = event["responsible_player_id"]
        _require(
            responsible_player in player_team,
            Code.INVALID_COMPLETION,
            "off-roof responsible player is not in the saved roster",
            event,
        )
        expected_losing_team = player_team[responsible_player]
        _require(
            event["losing_team_id"] == expected_losing_team,
            Code.INVALID_COMPLETION,
            "off-roof losing team must be derived from the responsible player",
            event,
        )

    for decision in retoss_decisions:
        target_id = decision.get("target_event_id")
        if target_id is None:
            _require(
                decision["thrower_id"] in player_team
                and decision["throwing_team_id"]
                == player_team.get(decision["thrower_id"]),
                Code.INVALID_REPLAY,
                "standalone retoss team must be derived from the saved roster",
                decision,
            )
            continue
        target = by_id.get(target_id)
        _require(
            target is not None
            and target["kind"] == "observation"
            and target["sequence"] < decision["sequence"],
            Code.INVALID_REPLAY,
            "retoss target must be an earlier observation",
            decision,
        )
        _require(
            decision["thrower_id"] == target["thrower_id"]
            and decision["throwing_team_id"] == target["throwing_team_id"],
            Code.INVALID_REPLAY,
            "retoss attribution must match its target observation",
            decision,
        )

    for target_id, correction in corrections.items():
        target = by_id.get(target_id)
        _require(
            target is not None
            and target["kind"] != "correction"
            and target["sequence"] < correction["sequence"],
            Code.INVALID_CORRECTION,
            "correction target must be an earlier non-correction event",
            correction,
        )
        if correction["reason"] == "changed_ruling":
            _require(
                bool(correction.get("disputed_calls"))
                and correction.get("decision_basis") is not None,
                Code.INVALID_CORRECTION,
                "changed rulings require disputed calls and a decision basis",
                correction,
            )
        replacement = replacements.get(target_id)
        _require(
            not (
                target["kind"] in {"score_checkpoint", "completion"}
                or (
                    correction["reason"] == "changed_ruling"
                    and target["kind"] == "observation"
                )
            )
            or replacement is not None,
            Code.INVALID_CORRECTION,
            "this correction requires an atomic replacement",
            correction,
        )

    for target_id, replacement in replacements.items():
        correction = corrections.get(target_id)
        target = by_id.get(target_id)
        _require(
            correction is not None and target is not None,
            Code.INVALID_CORRECTION,
            "replacement requires a correction for its target",
            replacement,
        )
        _require(
            correction["sequence"] < replacement["sequence"]
            and command_key(correction) == command_key(replacement),
            Code.INVALID_COMMAND,
            "replacement must follow its correction in the same command",
            replacement,
        )
        allowed_kinds = (
            {"completion", "score_checkpoint"}
            if target["kind"] == "completion"
            else {target["kind"]}
        )
        _require(
            replacement["kind"] in allowed_kinds,
            Code.INVALID_CORRECTION,
            "replacement kind is incompatible with its logical slot",
            replacement,
        )
        if correction["reason"] == "changed_ruling" and target["kind"] == "observation":
            changed = set(target.get("characteristics") or []) ^ set(
                replacement.get("characteristics") or []
            )
            _require(
                changed <= set(correction["disputed_calls"]),
                Code.INVALID_CORRECTION,
                "changed ruling cannot alter an undisputed invalid call",
                replacement,
            )

    replays = [event for event in ordered if event.get("replay_of") is not None]
    for event in replays:
        target = by_id.get(event["replay_of"])
        _require(
            target is not None
            and target["kind"] == "retoss_decision"
            and target["sequence"] < event["sequence"]
            and event.get("replacement_for") is None,
            Code.INVALID_REPLAY,
            "replay must link to an earlier retoss decision and cannot be a replacement",
            event,
        )
        _require(
            command_key(target) != command_key(event),
            Code.INVALID_COMMAND,
            "a physical replay must be a later command",
            event,
        )
        _require(
            event["thrower_id"] == target["thrower_id"]
            and event["throwing_team_id"] == target["throwing_team_id"],
            Code.INVALID_REPLAY,
            "physical replay attribution must match its retoss decision",
            event,
        )
    def effective_event(event: Event) -> tuple[Event | None, bool]:
        if event["id"] in retosses_by_target:
            return event, True
        correction = corrections.get(event["id"])
        if correction is None:
            return event, False
        replacement = replacements.get(event["id"])
        return effective_event(replacement) if replacement else (None, False)

    def active_event(event: Event) -> Event | None:
        effective, was_retossed = effective_event(event)
        return None if was_retossed else effective

    logical_slots: list[tuple[str, Event]] = []
    for event in ordered:
        if (
            event["kind"] in {"correction", "retoss_decision"}
            or event.get("replacement_for") is not None
        ):
            continue
        active = active_event(event)
        if active is not None:
            logical_slots.append((event["id"], active))

    for _, event in logical_slots:
        _require(
            (event.get("replay_resolution_for") is None)
            == (event.get("replay_disposition") is None),
            Code.INVALID_REPLAY,
            "replay resolution target and disposition must be present together",
            event,
        )

    active_replays = [
        (root, event)
        for root, event in effective_event_roots(ordered)
        if root.get("replay_of") is not None
    ]
    active_replay_targets = [root["replay_of"] for root, _ in active_replays]
    _require(
        len(set(active_replay_targets)) == len(active_replay_targets),
        Code.INVALID_REPLAY,
        "a retoss decision may have only one physical replay",
        next(
            (
                event
                for root, event in active_replays
                if active_replay_targets.count(root["replay_of"]) > 1
            ),
            None,
        ),
    )
    for root, event in active_replays:
        target = by_id[root["replay_of"]]
        _require(
            not any(
                target["sequence"] < by_id[candidate_root]["sequence"] < root["sequence"]
                and candidate["kind"]
                in {"observation", "score_checkpoint", "completion"}
                for candidate_root, candidate in logical_slots
            ),
            Code.INVALID_REPLAY,
            "physical replay must be the next score-bearing root event",
            event,
        )

    fulfilled: set[str] = set()
    for replay, effective_replay in active_replays:
        decision = by_id[replay["replay_of"]]
        _require(
            effective_replay["thrower_id"] == decision["thrower_id"]
            and effective_replay["throwing_team_id"]
            == decision["throwing_team_id"],
            Code.INVALID_REPLAY,
            "corrected replay attribution must match its retoss decision",
            effective_replay,
        )
        fulfilled.add(replay["replay_of"])
    resolutions = [
        (root_id, event)
        for root_id, event in logical_slots
        if event.get("replay_resolution_for") is not None
    ]
    resolved = {event["replay_resolution_for"] for _, event in resolutions}
    _require(
        len(resolved) == len(resolutions) and not (fulfilled & resolved),
        Code.INVALID_REPLAY,
        "a retoss decision must have exactly one fulfillment or resolution",
        resolutions[-1][1] if resolutions else None,
    )
    for root_id, event in resolutions:
        decision = by_id.get(event["replay_resolution_for"])
        _require(
            decision is not None
            and decision["kind"] == "retoss_decision"
            and decision["sequence"] < by_id[root_id]["sequence"],
            Code.INVALID_REPLAY,
            "replay resolution must target an earlier retoss decision",
            event,
        )
        _require(
            event["replay_disposition"] != "unobserved"
            or event["coverage"] in {"partial", "unknown"},
            Code.INVALID_REPLAY,
            "unobserved replay requires partial or unknown coverage",
            event,
        )
        _require(
            not any(
                decision["sequence"]
                < by_id[candidate_root]["sequence"]
                < by_id[root_id]["sequence"]
                and candidate["kind"]
                in {"observation", "score_checkpoint", "completion"}
                for candidate_root, candidate in logical_slots
            ),
            Code.INVALID_REPLAY,
            "replay resolution must occupy the next score-bearing root slot",
            event,
        )

    pending = {
        decision["id"]
        for decision in retoss_decisions
        if decision["id"] not in fulfilled and decision["id"] not in resolved
    }
    _require(
        len(pending) <= 1,
        Code.INVALID_REPLAY,
        "only one retoss may await fulfillment",
        by_id[next(iter(pending))] if len(pending) > 1 else None,
    )
    for target_id in pending:
        decision = by_id[target_id]
        _require(
            not any(
                by_id[root_id]["sequence"] > decision["sequence"]
                and event["kind"] in {"observation", "score_checkpoint", "completion"}
                for root_id, event in logical_slots
            ),
            Code.INVALID_STATE,
            "unrelated play is forbidden while awaiting a replay",
            decision,
        )

    for target_id, correction in corrections.items():
        target = by_id[target_id]
        replacement = replacements.get(target_id)
        if target["kind"] != "observation" or target["score_delta"] == (
            replacement["score_delta"] if replacement else [0, 0]
        ):
            continue
        prior_finals = [
            active
            for root_id, active in logical_slots
            if by_id[root_id]["kind"] == "completion"
            and by_id[root_id]["sequence"] < correction["sequence"]
        ]
        if prior_finals:
            reopened = prior_finals[-1]
            _require(
                reopened["kind"] == "score_checkpoint"
                and reopened["sequence"] < correction["sequence"],
                Code.INVALID_STATE,
                "score-changing correction after completion requires reopening first",
                correction,
            )
    for target_id, decision in retosses_by_target.items():
        if by_id[target_id]["score_delta"] == [0, 0]:
            continue
        prior_finals = [
            active
            for root_id, active in logical_slots
            if by_id[root_id]["kind"] == "completion"
            and by_id[root_id]["sequence"] < decision["sequence"]
        ]
        if prior_finals:
            reopened = prior_finals[-1]
            _require(
                reopened["kind"] == "score_checkpoint"
                and reopened["sequence"] < decision["sequence"],
                Code.INVALID_STATE,
                "score-changing retoss after completion requires reopening first",
                decision,
            )

    roots = [
        event
        for event in ordered
        if event["kind"] not in {"correction", "retoss_decision"}
        and event.get("replacement_for") is None
    ]

    def active_as_of(event: Event, cutoff: int) -> Event | None:
        _, retosses_at_cutoff = decision_view(cutoff)
        retoss = retosses_at_cutoff.get(event["id"])
        if retoss is not None and retoss["sequence"] <= cutoff:
            return None
        correction = corrections.get(event["id"])
        if correction is None or correction["sequence"] > cutoff:
            return event
        replacement = replacements.get(event["id"])
        if replacement is None or replacement["sequence"] > cutoff:
            return None
        return active_as_of(replacement, cutoff)

    coverage: list[str] = []
    previous_boundary: str | None = None
    for root_id, event in logical_slots:
        if event["kind"] not in {"score_checkpoint", "completion"}:
            continue
        _require(
            event["coverage_after"] == previous_boundary,
            Code.INVALID_COVERAGE,
            "coverage boundaries must form one unbroken root chain",
            event,
        )
        if event["coverage"] == "complete":
            cutoff = event["sequence"]
            start = by_id[previous_boundary]["sequence"] if previous_boundary else 0
            if previous_boundary:
                prior = active_as_of(by_id[previous_boundary], cutoff)
                _require(
                    prior is not None,
                    Code.INVALID_COVERAGE,
                    "correction cannot erase an earlier coverage boundary",
                    event,
                )
                expected = prior["score"][:]
            else:
                expected = [0, 0]
            for root in roots:
                if not (start < root["sequence"] < by_id[root_id]["sequence"]):
                    continue
                candidate = active_as_of(root, cutoff)
                if candidate is not None and candidate["kind"] == "observation":
                    expected = [
                        left + right
                        for left, right in zip(expected, candidate["score_delta"])
                    ]
            _require(
                event["score"] == expected,
                Code.INVALID_COVERAGE,
                f"complete interval score must reconcile to {expected}",
                event,
            )
        previous_boundary = root_id
        coverage.append(event["coverage"])

    score_bearing = [
        event
        for _, event in logical_slots
        if event["kind"]
        in {"observation", "score_checkpoint", "completion", "off_roof"}
    ]
    terminals = [
        index
        for index, event in enumerate(score_bearing)
        if event["kind"] in {"completion", "off_roof"}
    ]
    _require(
        not terminals or terminals == [len(score_bearing) - 1],
        Code.INVALID_STATE,
        "active terminal event must be the final score-bearing logical slot",
        score_bearing[terminals[0]] if terminals else None,
    )
    _require(
        not (pending and terminals),
        Code.INVALID_STATE,
        "a match cannot be completed while awaiting replay",
        by_id[next(iter(pending))] if pending else None,
    )

    score = [0, 0]
    stats: Counter[str] = Counter()
    player_outcomes = {player_id: Counter() for player_id in roster}
    fifa_goals: Counter[str] = Counter()
    fifa_kicks: Counter[str] = Counter()
    fifa_catches: Counter[str] = Counter()
    fifa_saves: Counter[str] = Counter()
    observations = 0
    termination_reason = None
    for _, event in logical_slots:
        if event["kind"] == "observation":
            score = [
                left + right for left, right in zip(score, event["score_delta"])
            ]
            stats[event["outcome"]] += 1
            player_outcomes[event["thrower_id"]][event["outcome"]] += 1
            if event["outcome"] == "fifa":
                fifa_kicks[event["fifa"]["kicker_id"]] += 1
                if event["fifa"]["finish"] == "goal":
                    fifa_goals[event["fifa"]["kicker_id"]] += 1
                elif event["fifa"]["finish"] == "kick_catch":
                    fifa_catches[event["fifa"]["catcher_id"]] += 1
                else:
                    fifa_saves[event["fifa"]["saver_id"]] += 1
            observations += 1
        elif event["kind"] == "off_roof":
            score = [0, 5] if event["losing_team_id"] == team_order[0] else [5, 0]
            termination_reason = "off_roof"
        elif event["kind"] in {"score_checkpoint", "completion"}:
            score = event["score"][:]
            _require(
                all(value >= 0 for value in score),
                Code.INVALID_COVERAGE,
                "boundary scores must be nonnegative",
                event,
            )
            if event["kind"] == "completion" and event["termination_reason"] == "target_reached":
                _require(
                    max(score) >= rules["target_score"]
                    and abs(score[0] - score[1]) >= rules["win_by"],
                    Code.INVALID_COMPLETION,
                    "target completion does not satisfy saved target and win-by",
                    event,
                )
            if event["kind"] == "completion":
                termination_reason = event["termination_reason"]

    projected_coverage = (
        "unknown"
        if not coverage
        else "partial"
        if "partial" in coverage
        else "unknown"
        if "unknown" in coverage
        else "complete"
    )
    return DiceLiveProjection(
        score=score,
        status=(
            "awaiting_replay"
            if pending
            else "completed"
            if terminals
            else "ready_to_finish"
            if max(score) >= rules["target_score"]
            and abs(score[0] - score[1]) >= rules["win_by"]
            else "active"
        ),
        termination_reason=termination_reason,
        coverage=projected_coverage,
        observations=observations,
        stats=dict(stats),
        player_stats={
            player_id: DiceLivePlayerStats(
                outcomes=DiceLiveOutcomeCounts(**player_outcomes[player_id]),
                fifa_goals=fifa_goals[player_id],
                fifa_kicks=fifa_kicks[player_id],
                fifa_catches=fifa_catches[player_id],
                fifa_saves=fifa_saves[player_id],
            )
            for player_id in roster
        },
    )
