import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dice.live_projector import project_dice_live
from dice.live_types import DiceLiveError, DiceLiveErrorCode, EventEnvelope

VECTORS = Path(__file__).parent / "fixtures" / "dice_live_projection_vectors.json"
RECORDED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _production_inputs(document, abbreviated_events):
    """Supply only the immutable envelope intentionally omitted by golden logs."""

    match = {"match_id": "fixture-match", **document["match_snapshot"]}
    events = []
    for abbreviated in abbreviated_events:
        sequence = abbreviated["sequence"]
        events.append(
            {
                "match_id": match["match_id"],
                "match_version": sequence,
                "client_command_id": f"event:{abbreviated['id']}",
                "command_index": 0,
                "recorded_by": "fixture-referee",
                "recorded_at": RECORDED_AT + timedelta(seconds=sequence),
                "match_elapsed_ms": sequence * 1_000,
                **abbreviated,
            }
        )
    return match, document["rules_snapshot"], events


def test_live_projection_contract_golden_vectors():
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert len(document["cases"]) == 31
    assert len(document["rejects"]) == 32

    for case in document["cases"]:
        match, rules, events = _production_inputs(document, case["events"])
        projection = project_dice_live(match, rules, events)
        # The original vectors remain the scoring/coverage compatibility contract;
        # roster-derived summaries are asserted separately below.
        assert projection.model_dump(exclude={"player_stats"}) == case["want"], case["name"]


def test_player_stats_have_stable_defaults_and_fifa_roles():
    document, events = _accepted_case(
        "v1 outcomes derive score from throw and participant roles"
    )
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)
    dumped = projection.model_dump(mode="json")

    assert dumped["player_stats"]["p1"] == {
        "outcomes": {
            "miss": 1, "caught": 1, "point": 1, "sink": 1,
            "self_sink": 1, "fifa": 3, "invalid": 1,
        },
        "fifa_goals": 0,
        "fifa_kicks": 0,
        "fifa_catches": 0,
        "fifa_saves": 0,
    }
    assert dumped["player_stats"]["p3"]["fifa_goals"] == 1
    assert dumped["player_stats"]["p3"]["fifa_kicks"] == 3
    assert dumped["player_stats"]["p3"]["fifa_catches"] == 0
    assert dumped["player_stats"]["p4"]["fifa_goals"] == 0
    assert dumped["player_stats"]["p4"]["fifa_kicks"] == 0
    assert dumped["player_stats"]["p4"]["fifa_catches"] == 1
    assert dumped["player_stats"]["p2"]["fifa_saves"] == 1
    assert set(dumped["player_stats"]) == {"p1", "p2", "p3", "p4"}


@pytest.mark.parametrize(
    ("case_name", "expected"),
    [
        (
            "whole throw correction changes sink to blamed self sink",
            {"sink": 0, "self_sink": 1},
        ),
        (
            "disputed low replay still counts its later point",
            {"invalid": 0, "point": 1},
        ),
        (
            "deleting a mistaken replay entry restores the pending decision",
            {"invalid": 0, "point": 0},
        ),
    ],
)
def test_player_stats_use_only_effective_logical_observations(case_name, expected):
    document, events = _accepted_case(case_name)
    match, rules, production_events = _production_inputs(document, events)

    outcomes = project_dice_live(match, rules, production_events).player_stats["p1"].outcomes

    for outcome, count in expected.items():
        assert getattr(outcomes, outcome) == count


def test_correction_moves_outcome_and_thrower_attribution_together():
    document, events = _accepted_case(
        "whole throw correction changes sink to blamed self sink"
    )
    events[2].update(
        thrower_id="p3",
        throwing_team_id="team2",
        outcome="point",
        score_delta=[0, 1],
    )
    match, rules, production_events = _production_inputs(document, events)

    player_stats = project_dice_live(match, rules, production_events).player_stats

    assert player_stats["p1"].outcomes.sink == 0
    assert player_stats["p3"].outcomes.point == 1


def test_removing_fifa_removes_thrower_and_participant_counters():
    document, events = _accepted_case(
        "v1 outcomes derive score from throw and participant roles"
    )
    fifa = {**events[5], "sequence": 1}
    removal = {
        "id": "remove-fifa",
        "sequence": 2,
        "kind": "correction",
        "target_event_id": fifa["id"],
        "reason": "mistaken_entry",
    }
    match, rules, production_events = _production_inputs(document, [fifa, removal])

    player_stats = project_dice_live(match, rules, production_events).player_stats

    assert player_stats["p1"].outcomes.fifa == 0
    assert player_stats["p3"].fifa_kicks == 0
    assert player_stats["p4"].fifa_catches == 0


def test_retossed_fifa_counts_only_the_physical_replay():
    document, events = _accepted_case("disputed low replay still counts its later point")
    events = events[:3]
    events[1]["disputed_calls"] = ["other"]
    for event in (events[0], events[2]):
        event.update(
            outcome="fifa",
            fifa={"finish": "goal", "kicker_id": "p3"},
            score_delta=[0, 1],
        )
        event.pop("characteristics", None)
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.observations == 1
    assert projection.player_stats["p1"].outcomes.fifa == 1
    assert projection.player_stats["p3"].fifa_goals == 1
    assert projection.player_stats["p3"].fifa_kicks == 1


def test_checkpoint_and_off_roof_add_no_player_counters():
    document, events = _accepted_case(
        "team one off-roof is an absolute five point loss"
    )
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)
    p1 = projection.player_stats["p1"]

    assert sum(p1.outcomes.model_dump().values()) == 1
    assert p1.outcomes.point == 1
    assert p1.fifa_goals == p1.fifa_kicks == p1.fifa_catches == p1.fifa_saves == 0


def test_live_projection_rejects_invalid_golden_logs_with_domain_errors():
    document = json.loads(VECTORS.read_text(encoding="utf-8"))

    for case in document["rejects"]:
        match, rules, events = _production_inputs(document, case["events"])
        with pytest.raises(DiceLiveError) as caught:
            project_dice_live(match, rules, events)
        error = caught.value
        assert error.code in DiceLiveErrorCode, case["name"]
        assert error.message, case["name"]
        assert error.event_id is not None, case["name"]
        assert error.sequence is not None, case["name"]
        assert str(error).startswith(f"{error.code}:"), case["name"]


def test_abbreviated_fixture_envelopes_are_not_valid_production_events():
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    match = {"match_id": "fixture-match", **document["match_snapshot"]}

    with pytest.raises(DiceLiveError) as caught:
        project_dice_live(match, document["rules_snapshot"], document["cases"][0]["events"])

    assert caught.value.code == DiceLiveErrorCode.INVALID_EVENT_SCHEMA


def test_base_event_envelope_is_rejected_with_identity():
    document, events = _accepted_case(
        "direct retoss decision records no invented official throw"
    )
    match, rules, production_events = _production_inputs(document, events)
    envelope = EventEnvelope.model_validate(
        {
            field: production_events[0][field]
            for field in EventEnvelope.model_fields
        }
    )

    with pytest.raises(DiceLiveError) as caught:
        project_dice_live(match, rules, [envelope])

    assert caught.value.code == DiceLiveErrorCode.INVALID_EVENT_SCHEMA
    assert caught.value.event_id == "d"
    assert caught.value.sequence == 1


def _accepted_case(name):
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    case = next(case for case in document["cases"] if case["name"] == name)
    return document, deepcopy(case["events"])


def test_ready_to_finish_is_nonterminal_and_has_no_reason():
    document, events = _accepted_case("normal target and win-by becomes ready without completion")
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.status == "ready_to_finish"
    assert projection.termination_reason is None
    assert not any(event["kind"] == "completion" for event in events)


def test_off_roof_is_absolute_terminal_without_invented_observation():
    document, events = _accepted_case("team one off-roof is an absolute five point loss")
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.score == [0, 5]
    assert projection.status == "completed"
    assert projection.termination_reason == "off_roof"
    assert projection.observations == 1
    assert projection.stats == {"point": 1}
    assert projection.player_stats["p1"].outcomes.point == 1


def test_hard_corrected_off_roof_reprojects_prior_score_and_status():
    document, events = _accepted_case("hard correction of off-roof restores earlier active projection")
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.score == [1, 0]
    assert projection.status == "active"
    assert projection.termination_reason is None


def test_physical_replay_attribution_must_match_retoss_decision():
    document, events = _accepted_case("direct retoss decision records no invented official throw")
    events[1]["thrower_id"] = "p3"
    events[1]["throwing_team_id"] = "team2"
    match, rules, production_events = _production_inputs(document, events)

    with pytest.raises(DiceLiveError) as caught:
        project_dice_live(match, rules, production_events)

    assert caught.value.code == DiceLiveErrorCode.INVALID_REPLAY
    assert caught.value.event_id == "o"


def test_replay_replacement_preserves_physical_replay_lineage():
    document, events = _accepted_case("deleting a mistaken replay entry restores the pending decision")
    events[3].update(client_command_id="replace-replay", command_index=0)
    events.append(
        {
            "id": "r2",
            "sequence": 5,
            "kind": "observation",
            "thrower_id": "p1",
            "throwing_team_id": "team1",
            "outcome": "point",
            "score_delta": [1, 0],
            "replacement_for": "o2",
            "client_command_id": "replace-replay",
            "command_index": 1,
        }
    )
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.status == "active"
    assert projection.score == [1, 0]
    assert projection.observations == 1


def test_retossed_replay_replacement_preserves_parent_lineage():
    document, events = _accepted_case(
        "deleting a mistaken replay entry restores the pending decision"
    )
    events[3].update(client_command_id="replace-replay", command_index=0)
    events.extend(
        [
            {
                "id": "r2",
                "sequence": 5,
                "kind": "observation",
                "thrower_id": "p1",
                "throwing_team_id": "team1",
                "outcome": "point",
                "score_delta": [1, 0],
                "replacement_for": "o2",
                "client_command_id": "replace-replay",
                "command_index": 1,
            },
            {
                "id": "d2",
                "sequence": 6,
                "kind": "retoss_decision",
                "thrower_id": "p1",
                "throwing_team_id": "team1",
                "target_event_id": "r2",
                "disputed_calls": ["other"],
                "decision_basis": "teams_agreed",
            },
        ]
    )
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.status == "awaiting_replay"
    assert projection.score == [0, 0]
    assert projection.observations == 0


def test_deleting_retoss_decision_restores_target_observation():
    document, events = _accepted_case("disputed low replay still counts its later point")
    events = events[:2]
    events.append(
        {
            "id": "delete-decision",
            "sequence": 3,
            "kind": "correction",
            "target_event_id": "c1",
            "reason": "mistaken_entry",
        }
    )
    match, rules, production_events = _production_inputs(document, events)

    projection = project_dice_live(match, rules, production_events)

    assert projection.status == "active"
    assert projection.score == [0, 0]
    assert projection.observations == 1
    assert projection.stats == {"invalid": 1}


def test_replay_replacement_attribution_must_match_retoss_decision():
    document, events = _accepted_case(
        "deleting a mistaken replay entry restores the pending decision"
    )
    events[3].update(client_command_id="replace-replay", command_index=0)
    events.append(
        {
            "id": "r2",
            "sequence": 5,
            "kind": "observation",
            "thrower_id": "p3",
            "throwing_team_id": "team2",
            "outcome": "point",
            "score_delta": [0, 1],
            "replacement_for": "o2",
            "client_command_id": "replace-replay",
            "command_index": 1,
        }
    )
    match, rules, production_events = _production_inputs(document, events)

    with pytest.raises(DiceLiveError) as caught:
        project_dice_live(match, rules, production_events)

    assert caught.value.code == DiceLiveErrorCode.INVALID_REPLAY
    assert caught.value.event_id == "r2"


@pytest.mark.parametrize("missing_field", ["replay_resolution_for", "replay_disposition"])
def test_replay_resolution_fields_must_be_present_together(missing_field):
    document, events = _accepted_case(
        "unobserved physical replay resolves through a partial checkpoint"
    )
    del events[2][missing_field]
    match, rules, production_events = _production_inputs(document, events)

    with pytest.raises(DiceLiveError) as caught:
        project_dice_live(match, rules, production_events)

    assert caught.value.code == DiceLiveErrorCode.INVALID_REPLAY
    assert caught.value.event_id == "k"
