"""Deterministic scene commands and uncached Supabase persistence."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from supabase import Client

from commons.schemas import CommonsSceneCommandRequest

SCENE_ID = "commons-home"
LAYOUT_VERSION = 1


class SceneCommandError(ValueError):
    """A command is invalid against the canonical scene model."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SceneConflictError(RuntimeError):
    """The scene changed before this command could be committed."""

    def __init__(self, code: str, current_version: int | None = None):
        super().__init__(code)
        self.code = code
        self.current_version = current_version


class SceneStoreError(RuntimeError):
    """The persistent scene store could not satisfy a request."""


def _coordinate(payload: dict[str, Any], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SceneCommandError("invalid_coordinate", f"{name} must be a finite number")
    coordinate = float(value)
    if not 0.08 <= coordinate <= 0.92:
        raise SceneCommandError("out_of_bounds", f"{name} must be between 0.08 and 0.92")
    return coordinate


def _text(payload: dict[str, Any], name: str, max_length: int = 64) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise SceneCommandError("invalid_payload", f"{name} is required")
    return value


def apply_scene_command(
    state: dict[str, Any], command: CommonsSceneCommandRequest
) -> dict[str, Any]:
    """Apply one validated command without mutating the input state."""

    next_state = deepcopy(state)
    objects = next_state.get("objects")
    actors = next_state.get("actors")
    if not isinstance(objects, dict) or not isinstance(actors, dict):
        raise SceneCommandError("invalid_state", "scene state is missing objects or actors")

    payload = command.payload
    if command.kind == "move_object":
        object_id = _text(payload, "object_id")
        scene_object = objects.get(object_id)
        if not isinstance(scene_object, dict):
            raise SceneCommandError("unknown_object", "object does not exist")
        if scene_object.get("movable") is not True:
            raise SceneCommandError("object_not_movable", "object cannot be moved")
        scene_object["x"] = _coordinate(payload, "x")
        scene_object["y"] = _coordinate(payload, "y")
        return next_state

    if command.kind == "walk_actor":
        actor_id = _text(payload, "actor_id")
        actor = actors.get(actor_id)
        if not isinstance(actor, dict):
            raise SceneCommandError("unknown_actor", "actor does not exist")
        prior_x = actor.get("x", 0.5)
        actor["x"] = _coordinate(payload, "x")
        actor["y"] = _coordinate(payload, "y")
        actor["facing"] = "east" if actor["x"] >= prior_x else "west"
        return next_state

    object_id = _text(payload, "object_id")
    state_key = _text(payload, "state_key", max_length=32)
    scene_object = objects.get(object_id)
    if not isinstance(scene_object, dict):
        raise SceneCommandError("unknown_object", "object does not exist")
    allowed_state = {
        "record-player": {"playing": bool},
        "floor-lamp": {"on": bool},
    }
    expected_type = allowed_state.get(object_id, {}).get(state_key)
    value = payload.get("value")
    if expected_type is None or type(value) is not expected_type:
        raise SceneCommandError("invalid_object_state", "object state transition is not allowed")
    scene_object.setdefault("state", {})[state_key] = value
    return next_state


def _scene_row(client: Client) -> dict[str, Any]:
    rows = (
        client.table("commons_scenes")
        .select("id,layout_version,version,state,updated_at")
        .eq("id", SCENE_ID)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise SceneStoreError("commons.scene_not_found")
    return rows[0]


def read_scene(client: Client) -> dict[str, Any]:
    return _scene_row(client)


def commit_scene_command(
    client: Client,
    actor_key: str,
    command: CommonsSceneCommandRequest,
) -> dict[str, Any]:
    row = _scene_row(client)
    next_state = apply_scene_command(row["state"], command)
    response = client.rpc(
        "commons_apply_command",
        {
            "p_scene_id": SCENE_ID,
            "p_actor_key": actor_key,
            "p_client_command_id": command.client_command_id,
            "p_expected_version": command.expected_version,
            "p_canonical_payload": {"kind": command.kind, "payload": command.payload},
            "p_resulting_state": next_state,
        },
    ).execute()
    result = response.data
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict):
        raise SceneStoreError("commons.invalid_store_response")
    if result.get("ok") is not True:
        code = result.get("error_code", "store_rejected")
        if code == "stale_version":
            raise SceneConflictError(code, result.get("current_version"))
        if code == "command_id_conflict":
            raise SceneConflictError(code)
        raise SceneStoreError(f"commons.{code}")
    return result
