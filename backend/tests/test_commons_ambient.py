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
            {"kind": "hold", "duration_ms": 176_400, "tile": [4, 4], "facing": "front_right"},
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
                {"kind": "hold", "duration_ms": 179000, "tile": [4, 4], "facing": "front_right"},
                {"kind": "hold", "duration_ms": 1000, "tile": [5, 4], "facing": "front_right"},
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
    assert pose["facing"] == "front_right"


def test_evaluates_time_before_epoch_with_mathematical_modulo():
    pose = evaluate_ambient_pose(PROGRAM, "host", PROGRAM["epoch_ms"] - 900)
    assert pose["u"] == 5
    assert pose["v"] == 4
    assert pose["facing"] == "back_left"


def test_disabled_program_returns_canonical_home():
    pose = evaluate_ambient_pose(
        {"enabled": False, "revision": 2, "reason": "invalidated"},
        "host",
        1,
        {"tile_x": 7, "tile_y": 8, "facing": "back_right"},
    )
    assert pose["mode"] == "home"
    assert (pose["tile_x"], pose["tile_y"], pose["facing"]) == (7, 8, "back_right")
