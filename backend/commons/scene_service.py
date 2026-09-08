"""Deterministic scene commands and uncached Supabase persistence."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from supabase import Client

from commons.schemas import CommonsSceneCommandRequest

SCENE_ID = "commons-home"
LAYOUT_VERSION = 7
GRID_COLUMNS = 16
GRID_ROWS = 16
GRID_WIDTH = 512
GRID_HEIGHT = 512
GRID_TILE_WIDTH = 32
GRID_TILE_HEIGHT = 20
GRID_ORIGIN_X = 256
GRID_ORIGIN_Y = 180
FOOTPRINTS = {
    "orange-sofa": {"cells": [(-1, 0), (0, 0), (1, 0)]},
    "green-loveseat": {"cells": [(0, 0), (1, 0)]},
    "red-armchair": {"cells": [(0, 0)]},
    "dining-table": {"cells": [(-1, 0), (0, 0), (1, 0)]},
    "dining-chair": {"cells": [(0, 0)]},
    "record-console": {"cells": [(-1, 0), (0, 0), (1, 0)]},
    "coffee-table": {"cells": [(-1, 0), (0, 0)]},
    "area-rug": {
        "cells": [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0)],
        "blocks_movement": False,
    },
    "floor-lamp": {"cells": [(0, 0)]},
    "topiary": {"cells": [(0, 0)]},
    "palm": {"cells": [(0, 0)]},
    "bar-stool": {"cells": [(0, 0)]},
}


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


def _tile_coordinate(payload: dict[str, Any], name: str, maximum: int) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SceneCommandError("invalid_tile", f"{name} must be an integer tile coordinate")
    if not 0 <= value < maximum:
        raise SceneCommandError("out_of_bounds", f"{name} must be between 0 and {maximum - 1}")
    return value


def _round_tile(value: float) -> int:
    return math.floor(value + 0.5)


def _normalized_to_tile(x: float, y: float) -> tuple[int, int]:
    pixel_x = x * GRID_WIDTH
    pixel_y = y * GRID_HEIGHT
    u = (pixel_x - GRID_ORIGIN_X) / (GRID_TILE_WIDTH / 2)
    v = (pixel_y - GRID_ORIGIN_Y) / (GRID_TILE_HEIGHT / 2)
    tile_x = max(0, min(GRID_COLUMNS - 1, _round_tile((u + v) / 2)))
    tile_y = max(0, min(GRID_ROWS - 1, _round_tile((v - u) / 2)))
    return tile_x, tile_y


def _tile_to_normalized(tile_x: int, tile_y: int) -> tuple[float, float]:
    pixel_x = GRID_ORIGIN_X + (tile_x - tile_y) * (GRID_TILE_WIDTH / 2)
    pixel_y = GRID_ORIGIN_Y + (tile_x + tile_y) * (GRID_TILE_HEIGHT / 2)
    return pixel_x / GRID_WIDTH, pixel_y / GRID_HEIGHT


def _command_tiles(payload: dict[str, Any]) -> tuple[int, int]:
    if "tile_x" in payload or "tile_y" in payload:
        return (
            _tile_coordinate(payload, "tile_x", GRID_COLUMNS),
            _tile_coordinate(payload, "tile_y", GRID_ROWS),
        )
    # Accept one legacy normalized command shape while old browsers roll over;
    # the resulting canonical state is still tile-based.
    return _normalized_to_tile(_coordinate(payload, "x"), _coordinate(payload, "y"))


def _entity_tile(entity: dict[str, Any]) -> tuple[int, int]:
    if isinstance(entity.get("tile_x"), int) and isinstance(entity.get("tile_y"), int):
        return entity["tile_x"], entity["tile_y"]
    return _normalized_to_tile(
        float(entity.get("x", 0.5)),
        float(entity.get("y", 0.5)),
    )


def _entity_footprint(entity: dict[str, Any]) -> dict[str, Any]:
    configured = entity.get("footprint")
    fallback = FOOTPRINTS.get(entity.get("asset"), {"cells": [(0, 0)]})
    cells = configured.get("cells") if isinstance(configured, dict) else None
    return {
        "cells": cells if isinstance(cells, list) else fallback["cells"],
        "blocks_movement": (
            configured.get("blocks_movement")
            if isinstance(configured, dict) and "blocks_movement" in configured
            else fallback.get("blocks_movement", True)
        ),
    }


def _entity_cells(entity: dict[str, Any], tile_x: int, tile_y: int) -> set[tuple[int, int]]:
    return {
        (tile_x + int(offset[0]), tile_y + int(offset[1]))
        for offset in _entity_footprint(entity)["cells"]
        if isinstance(offset, list | tuple) and len(offset) == 2
    }


def _tile_is_blocked(
    state: dict[str, Any], entity: dict[str, Any], tile_x: int, tile_y: int
) -> bool:
    candidate = _entity_cells(entity, tile_x, tile_y)
    if any(
        cell[0] < 0 or cell[0] >= GRID_COLUMNS or cell[1] < 0 or cell[1] >= GRID_ROWS
        for cell in candidate
    ):
        return True
    grid = state.get("grid")
    blocked = grid.get("blocked", []) if isinstance(grid, dict) else []
    return any(tuple(entry) in candidate for entry in blocked if isinstance(entry, list) and len(entry) == 2)


def _tile_is_available(
    state: dict[str, Any],
    tile_x: int,
    tile_y: int,
    *,
    entity_type: str,
    entity_id: str,
) -> bool:
    moving_entities = state.get("objects" if entity_type == "object" else "actors", {})
    moving_entity = moving_entities.get(entity_id, {}) if isinstance(moving_entities, dict) else {}
    candidate = _entity_cells(moving_entity, tile_x, tile_y)
    objects = state.get("objects", {})
    for object_id, scene_object in objects.items():
        if entity_type == "object" and object_id == entity_id:
            continue
        if not isinstance(scene_object, dict) or not _entity_footprint(scene_object)["blocks_movement"]:
            continue
        if _entity_cells(scene_object, *_entity_tile(scene_object)) & candidate:
            return False

    actors = state.get("actors", {})
    for actor_id, actor in actors.items():
        if entity_type == "actor" and actor_id == entity_id:
            continue
        if isinstance(actor, dict) and _entity_cells(actor, *_entity_tile(actor)) & candidate:
            return False
    return True


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
        tile_x, tile_y = _command_tiles(payload)
        if _tile_is_blocked(next_state, scene_object, tile_x, tile_y):
            raise SceneCommandError("tile_blocked", "that tile is part of the room shell")
        if not _tile_is_available(
            next_state,
            tile_x,
            tile_y,
            entity_type="object",
            entity_id=object_id,
        ):
            raise SceneCommandError("tile_occupied", "that tile is already occupied")
        scene_object["tile_x"] = tile_x
        scene_object["tile_y"] = tile_y
        scene_object["x"], scene_object["y"] = _tile_to_normalized(tile_x, tile_y)
        return next_state

    if command.kind == "walk_actor":
        actor_id = _text(payload, "actor_id")
        actor = actors.get(actor_id)
        if not isinstance(actor, dict):
            raise SceneCommandError("unknown_actor", "actor does not exist")
        tile_x, tile_y = _command_tiles(payload)
        prior_tile_x = actor.get("tile_x")
        prior_tile_y = actor.get("tile_y")
        if not isinstance(prior_tile_x, int) or not isinstance(prior_tile_y, int):
            prior_tile_x, prior_tile_y = _normalized_to_tile(
                _coordinate(actor, "x") if "x" in actor else 0.5,
                _coordinate(actor, "y") if "y" in actor else 0.5,
            )
        if abs(tile_x - prior_tile_x) + abs(tile_y - prior_tile_y) != 1:
            raise SceneCommandError("non_adjacent_move", "actors move one tile at a time")
        if _tile_is_blocked(next_state, actor, tile_x, tile_y):
            raise SceneCommandError("tile_blocked", "that tile is part of the room shell")
        if not _tile_is_available(
            next_state,
            tile_x,
            tile_y,
            entity_type="actor",
            entity_id=actor_id,
        ):
            raise SceneCommandError("tile_occupied", "that tile is already occupied")
        actor["tile_x"] = tile_x
        actor["tile_y"] = tile_y
        actor["x"], actor["y"] = _tile_to_normalized(tile_x, tile_y)
        if tile_x > prior_tile_x:
            actor["facing"] = "east"
        elif tile_x < prior_tile_x:
            actor["facing"] = "west"
        elif tile_y < prior_tile_y:
            actor["facing"] = "north"
        elif tile_y > prior_tile_y:
            actor["facing"] = "south"
        return next_state

    if command.kind == "rotate_object":
        object_id = _text(payload, "object_id")
        scene_object = objects.get(object_id)
        if not isinstance(scene_object, dict):
            raise SceneCommandError("unknown_object", "object does not exist")
        if scene_object.get("movable") is not True:
            raise SceneCommandError("object_not_movable", "object cannot be rotated")
        orientation = payload.get("orientation")
        if orientation not in {"north", "south"}:
            raise SceneCommandError("invalid_orientation", "orientation must be north or south")
        scene_object["orientation"] = orientation
        return next_state

    object_id = _text(payload, "object_id")
    state_key = _text(payload, "state_key", max_length=32)
    scene_object = objects.get(object_id)
    if not isinstance(scene_object, dict):
        raise SceneCommandError("unknown_object", "object does not exist")
    allowed_state = {
        "record-console": {"playing": bool},
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
