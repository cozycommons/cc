from copy import deepcopy

import pytest

from commons.schemas import CommonsSceneCommandRequest
from commons.scene_service import (
    SceneCommandError,
    SceneConflictError,
    apply_scene_command,
    commit_scene_command,
)


STATE = {
    "schema_version": 2,
    "grid": {"columns": 16, "rows": 16, "blocked": []},
    "objects": {
        "record-console": {
            "id": "record-console", "asset": "record-console", "movable": True, "tile_x": 3, "tile_y": 4,
            "state": {"playing": False},
        },
        "fixed-bookcase": {
            "id": "fixed-bookcase", "movable": False, "tile_x": 5, "tile_y": 3,
            "state": {},
        },
    },
    "actors": {"host": {"id": "host", "tile_x": 5, "tile_y": 5, "facing": "south"}},
}


def command(kind, payload):
    return CommonsSceneCommandRequest(
        client_command_id="command-1", expected_version=0, kind=kind, payload=payload
    )


def test_move_object_is_pure_and_updates_canonical_tile_coordinates():
    next_state = apply_scene_command(
        STATE, command("move_object", {"object_id": "record-console", "tile_x": 6, "tile_y": 7})
    )

    assert next_state["objects"]["record-console"]["tile_x"] == 6
    assert next_state["objects"]["record-console"]["tile_y"] == 7
    assert STATE["objects"]["record-console"]["tile_x"] == 3


def test_actor_walk_updates_facing_and_position():
    next_state = apply_scene_command(
        STATE, command("walk_actor", {"actor_id": "host", "tile_x": 6, "tile_y": 5})
    )

    assert next_state["actors"]["host"]["facing"] == "east"
    assert next_state["actors"]["host"]["tile_y"] == 5


def test_actor_walk_rejects_non_adjacent_steps():
    with pytest.raises(SceneCommandError) as error:
        apply_scene_command(
            STATE, command("walk_actor", {"actor_id": "host", "tile_x": 7, "tile_y": 5})
        )
    assert error.value.code == "non_adjacent_move"


def test_rotate_object_updates_persistent_orientation():
    next_state = apply_scene_command(
        STATE,
        command("rotate_object", {"object_id": "record-console", "orientation": "north"}),
    )

    assert next_state["objects"]["record-console"]["orientation"] == "north"


def test_rotate_object_rejects_unknown_orientation():
    with pytest.raises(SceneCommandError) as error:
        apply_scene_command(
            STATE,
            command("rotate_object", {"object_id": "record-console", "orientation": "east"}),
        )
    assert error.value.code == "invalid_orientation"


@pytest.mark.parametrize(
    "kind,payload,code",
    [
        ("move_object", {"object_id": "fixed-bookcase", "x": 0.5, "y": 0.5}, "object_not_movable"),
        ("move_object", {"object_id": "record-console", "tile_x": 16, "tile_y": 5}, "out_of_bounds"),
        ("set_object_state", {"object_id": "record-console", "state_key": "on", "value": True}, "invalid_object_state"),
    ],
)
def test_invalid_commands_are_rejected(kind, payload, code):
    with pytest.raises(SceneCommandError) as error:
        apply_scene_command(STATE, command(kind, payload))
    assert error.value.code == code


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, row):
        self.row = row

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return _Response([self.row])


class _Client:
    def __init__(self, result):
        self.result = result
        self.rpc_calls = []

    def table(self, _name):
        return _Query({"id": "commons-home", "version": 0, "state": STATE})

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _Query(self.result)


def test_commit_sends_the_canonical_next_state_to_the_database_function():
    client = _Client({
        "ok": True, "scene_id": "commons-home", "client_command_id": "command-1",
        "accepted_version": 1, "version": 1, "replayed": False, "state": STATE,
    })
    result = commit_scene_command(client, "browser-1", command(
        "move_object", {"object_id": "record-console", "tile_x": 6, "tile_y": 7}
    ))

    assert result["version"] == 1
    assert client.rpc_calls[0][0] == "commons_apply_command"
    assert client.rpc_calls[0][1]["p_resulting_state"]["objects"]["record-console"]["tile_x"] == 6


def test_commit_turns_a_database_version_mismatch_into_a_conflict():
    client = _Client({"ok": False, "error_code": "stale_version", "current_version": 4})

    with pytest.raises(SceneConflictError) as error:
        commit_scene_command(client, "browser-1", command(
            "walk_actor", {"actor_id": "host", "tile_x": 6, "tile_y": 5}
        ))

    assert error.value.current_version == 4


def test_commands_reject_occupied_and_reserved_tiles():
    with pytest.raises(SceneCommandError, match="already occupied") as occupied:
        apply_scene_command(
            STATE,
            command("move_object", {"object_id": "record-console", "tile_x": 5, "tile_y": 3}),
        )
    assert occupied.value.code == "tile_occupied"

    blocked_state = deepcopy(STATE)
    blocked_state["grid"]["blocked"] = [[6, 7]]
    with pytest.raises(SceneCommandError) as blocked:
        apply_scene_command(
            blocked_state,
            command("move_object", {"object_id": "record-console", "tile_x": 6, "tile_y": 7}),
        )
    assert blocked.value.code == "tile_blocked"


def test_large_furniture_footprint_reserves_neighboring_tiles():
    with pytest.raises(SceneCommandError) as error:
        apply_scene_command(
            STATE,
            command("move_object", {"object_id": "record-console", "tile_x": 4, "tile_y": 5}),
        )
    assert error.value.code == "tile_occupied"

    with pytest.raises(SceneCommandError) as edge:
        apply_scene_command(
            STATE,
            command("move_object", {"object_id": "record-console", "tile_x": 0, "tile_y": 5}),
        )
    assert edge.value.code == "tile_blocked"
