"""Validation and deterministic evaluation for the Commons ambient score."""

from __future__ import annotations

import math
from typing import Any

from commons.contracts import SCENE_CONTRACT

_WORLD = SCENE_CONTRACT["world"]
GRID_COLUMNS = int(_WORLD["columns"])
GRID_ROWS = int(_WORLD["rows"])
MAX_DURATION_MS = 24 * 60 * 60 * 1000
MAX_WALK_MS = 20 * 1000
VALID_VIEWS = set(SCENE_CONTRACT["actor_views"].values())
VIEW_BY_DELTA = {
    tuple(int(value) for value in key.split(",")): view
    for key, view in SCENE_CONTRACT["actor_views"].items()
}


class AmbientProgramError(ValueError):
    """A schedule cannot be safely evaluated against the Commons grid."""


def _is_int(value: Any) -> bool:
    """Return whether value is an integer rather than JSON's boolean subtype."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    """Accept only finite JSON numbers, including arbitrarily sized integers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int):
        return True
    return math.isfinite(value)


def _tile(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    u, v = value
    if (
        not _is_int(u)
        or not _is_int(v)
        or not 0 <= u < GRID_COLUMNS
        or not 0 <= v < GRID_ROWS
    ):
        return None
    return u, v


def _same_tile(first: tuple[int, int] | None, second: tuple[int, int] | None) -> bool:
    return first == second


def _state_tile(entity: Any) -> tuple[int, int] | None:
    if not isinstance(entity, dict):
        return None
    tile_x = entity.get("tile_x")
    tile_y = entity.get("tile_y")
    if tile_x is not None or tile_y is not None:
        if (
            not _is_int(tile_x)
            or not _is_int(tile_y)
        ):
            return None
        return (tile_x, tile_y) if 0 <= tile_x < GRID_COLUMNS and 0 <= tile_y < GRID_ROWS else None
    x = entity.get("x")
    y = entity.get("y")
    if (
        _is_finite_number(x)
        and _is_finite_number(y)
        and 0 <= x <= 1
        and 0 <= y <= 1
    ):
        try:
            pixel_x = float(x) * float(_WORLD["width"])
            pixel_y = float(y) * float(_WORLD["height"])
        except (OverflowError, TypeError):
            return None
        tile_u = (pixel_x - float(_WORLD["origin_x"])) / (float(_WORLD["tile_width"]) / 2)
        tile_v = (pixel_y - float(_WORLD["origin_y"])) / (float(_WORLD["tile_height"]) / 2)
        tile_x = math.floor(((tile_u + tile_v) / 2) + 0.5)
        tile_y = math.floor(((tile_v - tile_u) / 2) + 0.5)
        if 0 <= tile_x < GRID_COLUMNS and 0 <= tile_y < GRID_ROWS:
            return tile_x, tile_y
    return None


def _entity_footprint(entity: Any) -> tuple[list[tuple[int, int]], bool]:
    if not isinstance(entity, dict):
        raise AmbientProgramError("invalid scene entity")

    asset = entity.get("asset")
    fallback = SCENE_CONTRACT.get("footprints", {}).get(asset, {"cells": [[0, 0]]})
    if not isinstance(fallback, dict):
        raise AmbientProgramError("invalid entity footprint")

    configured = entity.get("footprint")
    if configured is not None and not isinstance(configured, dict):
        raise AmbientProgramError("invalid entity footprint")
    if isinstance(configured, dict) and "cells" in configured:
        cells = configured["cells"]
    else:
        cells = fallback.get("cells", [[0, 0]])
    if not isinstance(cells, list) or not cells:
        raise AmbientProgramError("invalid entity footprint")

    blocks_movement = (
        configured["blocks_movement"]
        if isinstance(configured, dict) and "blocks_movement" in configured
        else fallback.get("blocks_movement", True)
    )
    if not isinstance(blocks_movement, bool):
        raise AmbientProgramError("invalid entity footprint")

    parsed: set[tuple[int, int]] = set()
    for offset in cells:
        if (
            not isinstance(offset, (list, tuple))
            or len(offset) != 2
            or isinstance(offset[0], bool)
            or isinstance(offset[1], bool)
            or not _is_int(offset[0])
            or not _is_int(offset[1])
        ):
            raise AmbientProgramError("invalid entity footprint")
        parsed.add((offset[0], offset[1]))
    if not parsed:
        raise AmbientProgramError("invalid entity footprint")
    return list(parsed), blocks_movement


def _entity_cells(entity: Any, tile: tuple[int, int]) -> set[tuple[int, int]]:
    offsets, _ = _entity_footprint(entity)
    return {(tile[0] + offset[0], tile[1] + offset[1]) for offset in offsets}


def _blocks_movement(entity: Any) -> bool:
    _, blocks_movement = _entity_footprint(entity)
    return blocks_movement


def _cells_in_room(cells: set[tuple[int, int]]) -> bool:
    return all(
        0 <= cell[0] < GRID_COLUMNS and 0 <= cell[1] < GRID_ROWS
        for cell in cells
    )


def _cyclic_intervals_overlap(
    first: tuple[int, int], second: tuple[int, int], cycle: int
) -> bool:
    """Check closed occupancy intervals on the repeating cycle.

    Segment intervals are stored in the canonical [0, cycle] range. Comparing
    the second interval at one cycle on either side makes the cycle boundary
    explicit, including occupancy that meets at the repeated endpoint.
    """

    first_start, first_end = first
    second_start, second_end = second
    for shift in (-cycle, 0, cycle):
        shifted_start = second_start + shift
        shifted_end = second_end + shift
        if max(first_start, shifted_start) <= min(first_end, shifted_end):
            return True
    return False


def _validate_program_geometry(
    program: dict[str, Any],
    state: dict[str, Any],
    parsed_tracks: dict[str, dict[str, Any]] | None,
) -> None:
    """Validate authored supports against the room state before serving it."""

    if not isinstance(state, dict):
        raise AmbientProgramError("invalid scene state")

    grid = state.get("grid")
    if grid is not None and not isinstance(grid, dict):
        raise AmbientProgramError("invalid room grid")
    blocked_raw = grid.get("blocked", []) if isinstance(grid, dict) else []
    if not isinstance(blocked_raw, list):
        raise AmbientProgramError("invalid room blocker")
    blocked: set[tuple[int, int]] = set()
    for cell in blocked_raw:
        tile = _tile(cell)
        if tile is None:
            raise AmbientProgramError("invalid room blocker")
        blocked.add(tile)

    objects = state.get("objects")
    actors = state.get("actors")
    if not isinstance(objects, dict) or not isinstance(actors, dict):
        raise AmbientProgramError("scene entities are required for ambient validation")

    blocking_objects: list[set[tuple[int, int]]] = []
    for entity in objects.values():
        if not isinstance(entity, dict):
            raise AmbientProgramError("invalid scene object")
        if entity.get("visible") is False or entity.get("hidden") is True:
            continue
        tile = _state_tile(entity)
        if tile is None:
            raise AmbientProgramError("scene object has an invalid home anchor")
        cells = _entity_cells(entity, tile)
        if not _cells_in_room(cells):
            raise AmbientProgramError("scene object footprint is outside the room")
        if _blocks_movement(entity):
            blocking_objects.append(cells)

    actor_homes: dict[str, set[tuple[int, int]]] = {}
    for actor_id, actor in actors.items():
        tile = _state_tile(actor)
        if tile is None:
            raise AmbientProgramError("actor has an invalid home anchor")
        cells = _entity_cells(actor, tile)
        if not _cells_in_room(cells):
            raise AmbientProgramError("actor home footprint is outside the room")
        if cells & blocked or any(cells & occupied for occupied in blocking_objects):
            raise AmbientProgramError("actor home anchor is blocked")
        actor_homes[actor_id] = cells

    actor_ids = list(actor_homes)
    for index, actor_id in enumerate(actor_ids):
        for other_id in actor_ids[index + 1 :]:
            if actor_homes[actor_id] & actor_homes[other_id]:
                raise AmbientProgramError("actor home anchors overlap")

    # Disabled programs have no tracks to validate, but their canonical homes
    # above still need to be safe before they can be displayed.
    if parsed_tracks is None:
        return

    if set(parsed_tracks) != set(actors):
        raise AmbientProgramError("ambient actor tracks do not match the scene")

    for actor_id, track in parsed_tracks.items():
        actor = actors.get(actor_id)
        if not isinstance(actor, dict):
            raise AmbientProgramError("ambient actor is missing from the scene")
        home_tile = _state_tile(actor)
        if home_tile is None:
            raise AmbientProgramError("actor has an invalid home anchor")
        if track["first"] != home_tile or track["last"] != home_tile:
            raise AmbientProgramError("ambient track does not return to its canonical home")

        route_cells: set[tuple[int, int]] = set()
        for occupancy in track["occupancies"]:
            occupied_cells: set[tuple[int, int]] = set()
            for waypoint in occupancy["waypoints"]:
                waypoint_cells = _entity_cells(actor, waypoint)
                if not _cells_in_room(waypoint_cells):
                    raise AmbientProgramError("ambient actor footprint leaves the room")
                if waypoint_cells & blocked or any(
                    waypoint_cells & occupied for occupied in blocking_objects
                ):
                    raise AmbientProgramError("ambient route intersects a blocker")
                occupied_cells.update(waypoint_cells)
                route_cells.update(waypoint_cells)
            occupancy["cells"] = occupied_cells

        track["route"] = route_cells

    actor_items = list(parsed_tracks.items())
    for index, (actor_id, track) in enumerate(actor_items):
        for other_id, other_track in actor_items[index + 1 :]:
            for occupancy in track["occupancies"]:
                for other_occupancy in other_track["occupancies"]:
                    if not occupancy["cells"] & other_occupancy["cells"]:
                        continue
                    if _cyclic_intervals_overlap(
                        (occupancy["start"], occupancy["end"]),
                        (other_occupancy["start"], other_occupancy["end"]),
                        int(program["cycle_ms"]),
                    ):
                        raise AmbientProgramError(
                            f"ambient occupancy intersects another actor ({actor_id}, {other_id})"
                        )


def _duration(segment: dict[str, Any]) -> int:
    if not isinstance(segment, dict):
        return 0
    if segment.get("kind") == "hold":
        duration = segment.get("duration_ms")
        return duration if _is_int(duration) and duration > 0 else 0
    durations = segment.get("edge_durations_ms")
    if not isinstance(durations, list) or any(
        not _is_int(duration) or duration <= 0 for duration in durations
    ):
        return 0
    return sum(durations)


def _validate_segment(segment: Any, previous: tuple[int, int] | None) -> tuple[tuple[int, int], int, list[tuple[int, int]], list[str]]:
    if not isinstance(segment, dict) or segment.get("kind") not in {"hold", "walk"}:
        raise AmbientProgramError("unknown segment kind")
    if segment["kind"] == "hold":
        tile = _tile(segment.get("tile"))
        duration = segment.get("duration_ms")
        facing = segment.get("facing")
        if tile is None or not _is_int(duration) or not 0 < duration <= MAX_DURATION_MS:
            raise AmbientProgramError("invalid hold segment")
        if facing not in VALID_VIEWS:
            raise AmbientProgramError("invalid hold facing")
        if previous is not None and tile != previous:
            raise AmbientProgramError("segment is disconnected")
        return tile, duration, [tile], [facing]

    waypoints_raw = segment.get("waypoints")
    durations = segment.get("edge_durations_ms")
    if not isinstance(waypoints_raw, list) or len(waypoints_raw) < 2 or not isinstance(durations, list) or len(durations) != len(waypoints_raw) - 1:
        raise AmbientProgramError("invalid walk shape")
    waypoints = [_tile(value) for value in waypoints_raw]
    if any(tile is None for tile in waypoints):
        raise AmbientProgramError("walk contains an invalid waypoint")
    typed_waypoints = [tile for tile in waypoints if tile is not None]
    if previous is not None and typed_waypoints[0] != previous:
        raise AmbientProgramError("walk is disconnected")
    views: list[str] = []
    total = 0
    for first, second, duration in zip(typed_waypoints, typed_waypoints[1:], durations):
        delta = (second[0] - first[0], second[1] - first[1])
        view = VIEW_BY_DELTA.get(delta)
        if view is None or not _is_int(duration) or not 0 < duration <= MAX_DURATION_MS:
            raise AmbientProgramError("invalid walk edge")
        views.append(view)
        total += duration
    if not 0 < total <= MAX_DURATION_MS:
        raise AmbientProgramError("invalid walk duration")
    return typed_waypoints[-1], total, typed_waypoints, views


def validate_ambient_program(
    program: Any,
    actor_ids: list[str] | tuple[str, ...] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(program, dict) and program.get("enabled") is False:
        if (
            _is_int(program.get("revision"))
            and program["revision"] >= 0
            and isinstance(program.get("reason"), str)
            and program["reason"] in {"legacy", "invalidated", "resting_only"}
        ):
            if state is not None:
                _validate_program_geometry(program, state, None)
            return {"valid": True, "disabled": True}
        raise AmbientProgramError("invalid disabled ambient state")
    if not isinstance(program, dict) or program.get("enabled") is not True:
        raise AmbientProgramError("ambient state must be explicitly enabled or disabled")
    if not _is_int(program.get("revision")) or program["revision"] < 0:
        raise AmbientProgramError("invalid ambient revision")
    if not _is_finite_number(program.get("epoch_ms")):
        raise AmbientProgramError("invalid ambient epoch")
    cycle = program.get("cycle_ms")
    if not _is_int(cycle) or cycle <= 0:
        raise AmbientProgramError("invalid ambient cycle")
    if not _is_int(program.get("seed")):
        raise AmbientProgramError("invalid ambient seed")
    tracks = program.get("actors")
    if not isinstance(tracks, dict):
        raise AmbientProgramError("ambient actors are required")
    if any(not isinstance(actor_id, str) for actor_id in tracks):
        raise AmbientProgramError("ambient actor ids are invalid")
    if actor_ids is not None:
        if not isinstance(actor_ids, (list, tuple)) or any(
            not isinstance(actor_id, str) for actor_id in actor_ids
        ):
            raise AmbientProgramError("ambient actor ids are invalid")
        if len(set(actor_ids)) != len(actor_ids) or set(tracks) != set(actor_ids):
            raise AmbientProgramError("ambient actor tracks do not match the scene")
    walk_intervals: list[tuple[int, int]] = []
    parsed_tracks: dict[str, dict[str, Any]] = {}
    for actor_id, segments in tracks.items():
        if not isinstance(segments, list) or not segments:
            raise AmbientProgramError("actor needs an ambient track")
        elapsed = 0
        previous = None
        first = None
        walking_duration = 0
        route_cells: set[tuple[int, int]] = set()
        hold_cells: set[tuple[int, int]] = set()
        occupancies: list[dict[str, Any]] = []
        for segment in segments:
            end, duration, waypoints, _ = _validate_segment(segment, previous)
            if first is None:
                first = waypoints[0]
            route_cells.update(waypoints)
            if segment.get("kind") == "hold":
                hold_cells.update(waypoints)
                occupancies.append(
                    {
                        "kind": "hold",
                        "start": elapsed,
                        "end": elapsed + duration,
                        "waypoints": (waypoints[0],),
                        "cells": set(),
                    }
                )
            if segment.get("kind") == "walk":
                walking_duration += duration
                walk_intervals.append((elapsed, elapsed + duration))
                edge_elapsed = elapsed
                for first_waypoint, second_waypoint, edge_duration in zip(
                    waypoints, waypoints[1:], segment["edge_durations_ms"]
                ):
                    occupancies.append(
                        {
                            "kind": "walk",
                            "start": edge_elapsed,
                            "end": edge_elapsed + edge_duration,
                            "waypoints": (first_waypoint, second_waypoint),
                            "cells": set(),
                        }
                    )
                    edge_elapsed += edge_duration
            elapsed += duration
            previous = end
        if elapsed != cycle:
            raise AmbientProgramError("actor track does not fill the cycle")
        if walking_duration > MAX_WALK_MS:
            raise AmbientProgramError("actor walks for too much of the cycle")
        if not _same_tile(first, previous):
            raise AmbientProgramError("ambient cycle wraps discontinuously")
        parsed_tracks[actor_id] = {
            "route": route_cells,
            "holds": hold_cells,
            "occupancies": occupancies,
            "first": first,
            "last": previous,
        }
    if state is not None:
        _validate_program_geometry(program, state, parsed_tracks)
    limit = program.get("max_walkers", 1)
    if not _is_int(limit) or limit < 1:
        raise AmbientProgramError("invalid walker limit")
    events: list[tuple[int, int]] = [(start, 1) for start, _ in walk_intervals] + [(end, -1) for _, end in walk_intervals]
    active = maximum = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        maximum = max(maximum, active)
    if maximum > limit:
        raise AmbientProgramError("ambient walk count exceeds program limit")
    return {"valid": True, "disabled": False}


def _disabled_pose(home: dict[str, Any] | None) -> dict[str, Any]:
    home = home if isinstance(home, dict) else {}
    tile_x = home.get("tile_x") if _is_int(home.get("tile_x")) else 0
    tile_y = home.get("tile_y") if _is_int(home.get("tile_y")) else 0
    return {
        "mode": "home",
        "tile_x": tile_x,
        "tile_y": tile_y,
        "u": float(tile_x),
        "v": float(tile_y),
        "facing": home.get("facing", "front_right"),
        "segment_index": -1,
        "edge_index": -1,
        "progress": 0.0,
    }


def evaluate_ambient_pose(program: dict[str, Any], actor_id: str, time_ms: float, home: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(program, dict) or program.get("enabled") is not True:
        return _disabled_pose(home)
    tracks = program.get("actors")
    track = tracks.get(actor_id) if isinstance(tracks, dict) else None
    cycle = program.get("cycle_ms")
    epoch = program.get("epoch_ms")
    if (
        not isinstance(track, list)
        or not track
        or not _is_int(cycle)
        or cycle <= 0
        or not _is_finite_number(epoch)
        or not _is_finite_number(time_ms)
    ):
        return _disabled_pose(home)

    parsed_segments: list[tuple[tuple[int, int], int, list[tuple[int, int]], list[str]]] = []
    elapsed = 0
    previous = None
    first = None
    try:
        for segment in track:
            end, duration, waypoints, views = _validate_segment(segment, previous)
            if first is None:
                first = waypoints[0]
            parsed_segments.append((end, duration, waypoints, views))
            elapsed += duration
            previous = end
    except (AmbientProgramError, KeyError, TypeError, ValueError):
        return _disabled_pose(home)
    if elapsed != cycle or first != previous:
        return _disabled_pose(home)
    try:
        remaining = ((time_ms - epoch) % cycle + cycle) % cycle
    except (OverflowError, TypeError, ValueError):
        return _disabled_pose(home)

    for segment_index, (end, duration, waypoints, views) in enumerate(parsed_segments):
        segment = track[segment_index]
        if remaining < duration or segment_index == len(parsed_segments) - 1:
            if segment.get("kind") == "hold":
                tile = waypoints[0]
                return {
                    "mode": "hold",
                    "tile_x": tile[0],
                    "tile_y": tile[1],
                    "u": float(tile[0]),
                    "v": float(tile[1]),
                    "facing": views[0],
                    "segment_index": segment_index,
                    "edge_index": -1,
                    "progress": remaining / duration if duration else 0.0,
                }
            elapsed = remaining
            for edge_index, edge_duration in enumerate(segment["edge_durations_ms"]):
                if elapsed < edge_duration or edge_index == len(segment["edge_durations_ms"]) - 1:
                    first, second = waypoints[edge_index], waypoints[edge_index + 1]
                    progress = min(1.0, elapsed / edge_duration) if edge_duration else 1.0
                    return {
                        "mode": "walk",
                        "tile_x": second[0],
                        "tile_y": second[1],
                        "u": first[0] + (second[0] - first[0]) * progress,
                        "v": first[1] + (second[1] - first[1]) * progress,
                        "facing": views[edge_index],
                        "segment_index": segment_index,
                        "edge_index": edge_index,
                        "progress": progress,
                    }
                elapsed -= edge_duration
        remaining -= duration
    return _disabled_pose(home)
