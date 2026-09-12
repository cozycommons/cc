import pytest

from commons.ambient import AmbientProgramError, evaluate_ambient_pose, validate_ambient_program


PROGRAM = {
    "enabled": True,
    "revision": 1,
    "epoch_ms": 1_800_000_000_000,
    "cycle_ms": 180_000,
    "seed": 42,
    "max_walkers": 1,
    "actors": {
        "host": [
            {"kind": "hold", "duration_ms": 176_400, "tile": [4, 4], "facing": "front"},
            {"kind": "walk", "waypoints": [[4, 4], [5, 4], [6, 4]], "edge_durations_ms": [900, 900]},
            {"kind": "walk", "waypoints": [[6, 4], [5, 4], [4, 4]], "edge_durations_ms": [900, 900]},
        ],
    },
}


def test_validates_complete_continuous_track():
    assert validate_ambient_program(PROGRAM, ["host"]) == {"valid": True, "disabled": False}


def test_rejects_disconnected_segments():
    invalid = {
        **PROGRAM,
        "actors": {
            "host": [
                    {"kind": "hold", "duration_ms": 179000, "tile": [4, 4], "facing": "front"},
                    {"kind": "hold", "duration_ms": 1000, "tile": [5, 4], "facing": "front"},
            ]
        },
    }
    with pytest.raises(AmbientProgramError, match="disconnected"):
        validate_ambient_program(invalid, ["host"])


def test_evaluates_fractional_position_and_direction():
    pose = evaluate_ambient_pose(PROGRAM, "host", PROGRAM["epoch_ms"] + 177300)
    assert pose["mode"] == "walk"
    assert pose["u"] == 5
    assert pose["v"] == 4
    assert pose["facing"] == "right"


def test_evaluates_time_before_epoch_with_mathematical_modulo():
    pose = evaluate_ambient_pose(PROGRAM, "host", PROGRAM["epoch_ms"] - 900)
    assert pose["u"] == 5
    assert pose["v"] == 4
    assert pose["facing"] == "left"


def test_disabled_program_returns_canonical_home():
    pose = evaluate_ambient_pose(
        {"enabled": False, "revision": 2, "reason": "invalidated"},
        "host",
        1,
        {"tile_x": 7, "tile_y": 8, "facing": "back"},
    )
    assert pose["mode"] == "home"
    assert (pose["tile_x"], pose["tile_y"], pose["facing"]) == (7, 8, "back")


def test_rejects_a_resident_that_walks_for_more_than_twenty_seconds():
    invalid = {
        **PROGRAM,
        "cycle_ms": 260_000,
        "actors": {
            "host": [
            {"kind": "hold", "duration_ms": 200_000, "tile": [4, 4], "facing": "front"},
                {"kind": "walk", "waypoints": [[4, 4], [5, 4]], "edge_durations_ms": [21_000]},
                {"kind": "walk", "waypoints": [[5, 4], [4, 4]], "edge_durations_ms": [21_000]},
            {"kind": "hold", "duration_ms": 18_000, "tile": [4, 4], "facing": "front"},
            ],
        },
    }
    with pytest.raises(AmbientProgramError, match="too much"):
        validate_ambient_program(invalid, ["host"])


def test_rejects_a_route_that_intersects_a_blocking_object():
    state = {
        "grid": {"blocked": []},
        "objects": {
            "console": {"asset": "record-console", "tile_x": 6, "tile_y": 4},
        },
        "actors": {"host": {"asset": "host", "tile_x": 4, "tile_y": 4}},
    }
    with pytest.raises(AmbientProgramError, match="intersects a blocker"):
        validate_ambient_program(PROGRAM, ["host"], state)


def test_rejects_a_route_that_intersects_another_resident_home():
    state = {
        "grid": {"blocked": []},
        "objects": {},
        "actors": {
            "host": {"asset": "host", "tile_x": 4, "tile_y": 4},
            "maker": {"asset": "maker", "tile_x": 5, "tile_y": 4},
        },
    }
    invalid = {
        **PROGRAM,
        "actors": {
            "host": PROGRAM["actors"]["host"],
            "maker": [{"kind": "hold", "duration_ms": 180_000, "tile": [5, 4], "facing": "front"}],
        },
    }
    with pytest.raises(AmbientProgramError, match="another actor"):
        validate_ambient_program(invalid, ["host", "maker"], state)


def test_rejects_a_disabled_program_with_an_unsafe_home_anchor():
    state = {
        "grid": {"blocked": [[4, 4]]},
        "objects": {},
        "actors": {"host": {"asset": "host", "tile_x": 4, "tile_y": 4}},
    }
    with pytest.raises(AmbientProgramError, match="home anchor"):
        validate_ambient_program({"enabled": False, "revision": 2, "reason": "resting_only"}, ["host"], state)


def _timed_outing(home, destination, start):
    return [
        {"kind": "hold", "duration_ms": start, "tile": home, "facing": "front"},
        {"kind": "walk", "waypoints": [home, destination, home], "edge_durations_ms": [1000, 1000]},
        {"kind": "hold", "duration_ms": 20000 - start - 2000, "tile": home, "facing": "front"},
    ]


def test_allows_shared_route_cells_at_different_times():
    state = {"objects": {}, "actors": {
        "host": {"asset": "host", "tile_x": 4, "tile_y": 4},
        "maker": {"asset": "maker", "tile_x": 5, "tile_y": 5},
    }}
    program = {**PROGRAM, "cycle_ms": 20000, "actors": {
        "host": _timed_outing([4, 4], [5, 4], 2000),
        "maker": _timed_outing([5, 5], [5, 4], 8000),
    }}
    assert validate_ambient_program(program, ["host", "maker"], state)["valid"]
    program["actors"]["maker"] = _timed_outing([5, 5], [5, 4], 2000)
    with pytest.raises(AmbientProgramError, match="another actor"):
        validate_ambient_program(program, ["host", "maker"], state)


def test_checks_whole_actor_footprint_at_route_waypoints():
    state = {"grid": {"blocked": [[6, 5]]}, "objects": {}, "actors": {
        "host": {"asset": "host", "tile_x": 4, "tile_y": 4,
                 "footprint": {"cells": [[0, 0], [0, 1]]}},
    }}
    with pytest.raises(AmbientProgramError, match="blocker"):
        validate_ambient_program(PROGRAM, ["host"], state)


@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_rejects_invalid_disabled_revisions(value):
    with pytest.raises(AmbientProgramError):
        validate_ambient_program({"enabled": False, "revision": value, "reason": "resting_only"})


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True])
def test_rejects_nonfinite_or_boolean_epoch(value):
    with pytest.raises(AmbientProgramError):
        validate_ambient_program({**PROGRAM, "epoch_ms": value})


def test_explicit_empty_actor_set_rejects_existing_tracks():
    with pytest.raises(AmbientProgramError, match="do not match"):
        validate_ambient_program(PROGRAM, [])
