import pytest

from dice.live_probability import (
    LiveProbabilityInput,
    project_live_history,
    project_live_projection,
    project_live_probability,
)
from dice.live_types import DiceLiveError, DiceLiveErrorCode, DiceLiveProjection, CallPolicy, SavedRules


def _input(**overrides):
    values = dict(
        match_version=3,
        team1_score=0,
        team2_score=0,
        target_score=11,
        win_by=2,
        pregame_team1_probability=0.5,
    )
    values.update(overrides)
    return LiveProbabilityInput(**values)


def test_projection_is_symmetric_and_versioned():
    result = project_live_probability(_input())
    assert result.team1 == pytest.approx(0.5)
    assert result.team2 == pytest.approx(0.5)
    assert result.match_version == 3
    assert result.model_id == "elo-score-composition"


def test_score_and_terminal_states_move_probability_monotonically():
    behind = project_live_probability(_input(team1_score=3, team2_score=7))
    ahead = project_live_probability(_input(team1_score=7, team2_score=3))
    won = project_live_probability(_input(team1_score=11, team2_score=4))
    assert ahead.team1 > 0.5 > behind.team1
    assert won.team1 == 1.0
    assert won.team2 == 0.0


def test_projection_adapter_uses_authoritative_score_and_rules_snapshot():
    projection = DiceLiveProjection(
        score=[7, 3], status="active", coverage="complete", observations=4, stats={}
    )
    rules = SavedRules(
        contract_version=1,
        ruleset_version=1,
        scoring_version=1,
        target_score=11,
        win_by=2,
        call_policy=CallPolicy(
            low_call_deadline="before_surface_contact",
            low_call_exceptions=[],
            short_boundary="center_line_is_short",
            midline_remedy="consume_attempt",
            dispute_authority="teams_or_designated_referee",
            uncertain_call_remedy="retoss",
        ),
    )
    result = project_live_projection(
        projection, rules, match_version=9, pregame_team1_probability=0.5
    )
    assert result.match_version == 9
    assert result.team1 > 0.5


@pytest.mark.parametrize(
    ("score", "expected"),
    [([3, 2], (1.0, 0.0)), ([1, 4], (0.0, 1.0))],
)
def test_completed_projection_is_terminal_even_below_target(score, expected):
    projection = DiceLiveProjection(
        score=score, status="completed", coverage="partial", observations=1,
        stats={}, termination_reason="mutual_end",
    )
    rules = SavedRules(
        contract_version=1, ruleset_version=1, scoring_version=1,
        target_score=11, win_by=2,
        call_policy=CallPolicy(
            low_call_deadline="before_surface_contact", low_call_exceptions=[],
            short_boundary="center_line_is_short", midline_remedy="consume_attempt",
            dispute_authority="teams_or_designated_referee", uncertain_call_remedy="retoss",
        ),
    )

    result = project_live_projection(
        projection, rules, match_version=10, pregame_team1_probability=0.7
    )

    assert (result.team1, result.team2) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"match_version": 0},
        {"team1_score": -1},
        {"target_score": 0},
        {"pregame_team1_probability": 1.1},
    ],
)
def test_invalid_inputs_raise_stable_domain_error(overrides):
    with pytest.raises(DiceLiveError) as error:
        project_live_probability(_input(**overrides))
    assert error.value.code == DiceLiveErrorCode.INVALID_STATE


def test_history_uses_command_boundaries_and_shows_correction_as_a_new_moment():
    match = {
        "match_id": "m1", "team_order": ["blue", "clay"],
        "teams": {"blue": ["a", "b"], "clay": ["c", "d"]},
    }
    rules = {
        "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
        "target_score": 11, "win_by": 2,
        "call_policy": {
            "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
            "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
        },
    }
    common = {
        "match_id": "m1", "recorded_by": "ref", "recorded_at": "2026-08-24T12:00:00Z",
        "match_elapsed_ms": 0,
    }
    events = [
        {**common, "id": "e1", "match_version": 1, "sequence": 1,
         "client_command_id": "c1", "command_index": 0, "kind": "observation",
         "thrower_id": "a", "throwing_team_id": "blue", "outcome": "point",
         "score_delta": [1, 0]},
        {**common, "id": "e2", "match_version": 2, "sequence": 2,
         "client_command_id": "c2", "command_index": 0, "kind": "correction",
         "target_event_id": "e1", "reason": "mistaken_entry"},
        {**common, "id": "e3", "match_version": 2, "sequence": 3,
         "client_command_id": "c2", "command_index": 1, "kind": "observation",
         "thrower_id": "c", "throwing_team_id": "clay", "outcome": "point",
         "score_delta": [0, 1], "replacement_for": "e1"},
    ]

    points = project_live_history(match, rules, events, pregame_team1_probability=0.5)

    assert [point.match_version for point in points] == [0, 1, 2]
    assert [point.score for point in points] == [(0, 0), (1, 0), (0, 1)]
    assert points[1].swing > 0
    assert points[2].swing < 0
    assert points[2].kind == "correction"
    assert points[2].outcome == "point"
    assert points[2].thrower_id == "c"


def test_history_names_reopening_a_final_result_as_its_own_moment():
    match = {
        "match_id": "m1", "team_order": ["blue", "clay"],
        "teams": {"blue": ["a", "b"], "clay": ["c", "d"]},
    }
    rules = {
        "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
        "target_score": 11, "win_by": 2,
        "call_policy": {
            "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
            "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
        },
    }
    common = {
        "match_id": "m1", "recorded_by": "ref", "recorded_at": "2026-08-24T12:00:00Z",
        "match_elapsed_ms": 0,
    }
    events = [
        {**common, "id": "final", "match_version": 1, "sequence": 1,
         "client_command_id": "c1", "command_index": 0, "kind": "completion",
         "score": [1, 0], "coverage": "partial", "coverage_after": None,
         "replacement_for": None, "replay_resolution_for": None, "replay_disposition": None,
         "termination_reason": "other"},
        {**common, "id": "undo-final", "match_version": 2, "sequence": 2,
         "client_command_id": "c2", "command_index": 0, "kind": "correction",
         "target_event_id": "final", "reason": "mistaken_entry"},
        {**common, "id": "open-again", "match_version": 2, "sequence": 3,
         "client_command_id": "c2", "command_index": 1, "kind": "score_checkpoint",
         "score": [1, 0], "coverage": "partial", "coverage_after": None,
         "replacement_for": "final", "replay_resolution_for": None, "replay_disposition": None},
    ]

    points = project_live_history(match, rules, events, pregame_team1_probability=0.5)

    assert points[-1].kind == "reopen"
    assert points[-1].score == (1, 0)


def test_history_exposes_saved_fifa_finish_and_hero_without_probability_swing():
    match = {
        "match_id": "m1", "team_order": ["blue", "clay"],
        "teams": {"blue": ["a", "b"], "clay": ["c", "d"]},
    }
    rules = {
        "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
        "target_score": 11, "win_by": 2,
        "call_policy": {
            "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
            "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
        },
    }
    event = {
        "id": "fifa-save", "match_id": "m1", "match_version": 1, "sequence": 1,
        "client_command_id": "c1", "command_index": 0, "kind": "observation",
        "recorded_by": "ref", "recorded_at": "2026-08-24T12:00:00Z",
        "match_elapsed_ms": 0, "thrower_id": "a", "throwing_team_id": "blue",
        "outcome": "fifa", "score_delta": [0, 0],
        "fifa": {"finish": "goal_saved", "kicker_id": "c", "saver_id": "b"},
    }

    points = project_live_history(match, rules, [event], pregame_team1_probability=0.5)

    assert points[-1].score == (0, 0)
    assert points[-1].swing == 0
    assert points[-1].fifa_finish == "goal_saved"
    assert points[-1].fifa_actor_id == "b"
