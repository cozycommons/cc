import pytest

from commons.schemas import CommonsSceneCommandRequest
from commons.scene_service import (
    SceneCommandError,
    SceneConflictError,
    apply_scene_command,
    commit_scene_command,
)


STATE = {
    "schema_version": 1,
    "objects": {
        "record-player": {
            "id": "record-player", "movable": True, "x": 0.3, "y": 0.4,
            "state": {"playing": False},
        },
        "fixed-bookcase": {
            "id": "fixed-bookcase", "movable": False, "x": 0.5, "y": 0.3,
            "state": {},
        },
    },
    "actors": {"host": {"id": "host", "x": 0.5, "y": 0.5, "facing": "south"}},
}


def command(kind, payload):
    return CommonsSceneCommandRequest(
        client_command_id="command-1", expected_version=0, kind=kind, payload=payload
    )


def test_move_object_is_pure_and_updates_logical_coordinates():
    next_state = apply_scene_command(
        STATE, command("move_object", {"object_id": "record-player", "x": 0.62, "y": 0.71})
    )

    assert next_state["objects"]["record-player"]["x"] == 0.62
    assert STATE["objects"]["record-player"]["x"] == 0.3


def test_actor_walk_updates_facing_and_position():
    next_state = apply_scene_command(
        STATE, command("walk_actor", {"actor_id": "host", "x": 0.7, "y": 0.6})
    )

    assert next_state["actors"]["host"]["facing"] == "east"
    assert next_state["actors"]["host"]["y"] == 0.6


@pytest.mark.parametrize(
    "kind,payload,code",
    [
        ("move_object", {"object_id": "fixed-bookcase", "x": 0.5, "y": 0.5}, "object_not_movable"),
        ("move_object", {"object_id": "record-player", "x": 0.99, "y": 0.5}, "out_of_bounds"),
        ("set_object_state", {"object_id": "record-player", "state_key": "on", "value": True}, "invalid_object_state"),
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
        "move_object", {"object_id": "record-player", "x": 0.62, "y": 0.71}
    ))

    assert result["version"] == 1
    assert client.rpc_calls[0][0] == "commons_apply_command"
    assert client.rpc_calls[0][1]["p_resulting_state"]["objects"]["record-player"]["x"] == 0.62


def test_commit_turns_a_database_version_mismatch_into_a_conflict():
    client = _Client({"ok": False, "error_code": "stale_version", "current_version": 4})

    with pytest.raises(SceneConflictError) as error:
        commit_scene_command(client, "browser-1", command(
            "walk_actor", {"actor_id": "host", "x": 0.62, "y": 0.71}
        ))

    assert error.value.current_version == 4
