"""Validation and deterministic evaluation for the Commons ambient score."""

from __future__ import annotations

import math
from typing import Any

GRID_COLUMNS = 16
GRID_ROWS = 16
MAX_DURATION_MS = 24 * 60 * 60 * 1000
VALID_VIEWS = {"front_right", "front_left", "back_left", "back_right"}
VIEW_BY_DELTA = {
    (1, 0): "front_right",
    (0, 1): "front_left",
    (-1, 0): "back_left",
    (0, -1): "back_right",
}


class AmbientProgramError(ValueError):
    """A schedule cannot be safely evaluated against the Commons grid."""


def _tile(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    u, v = value
    if (
        isinstance(u, bool)
        or isinstance(v, bool)
        or not isinstance(u, int)
        or not isinstance(v, int)
        or not 0 <= u < GRID_COLUMNS
        or not 0 <= v < GRID_ROWS
    ):
        return None
    return u, v


def _same_tile(first: tuple[int, int] | None, second: tuple[int, int] | None) -> bool:
    return first == second


def _duration(segment: dict[str, Any]) -> int:
    if segment.get("kind") == "hold":
        return int(segment["duration_ms"])
    return sum(segment["edge_durations_ms"])


def _validate_segment(segment: Any, previous: tuple[int, int] | None) -> tuple[tuple[int, int], int, list[tuple[int, int]], list[str]]:
    if not isinstance(segment, dict) or segment.get("kind") not in {"hold", "walk"}:
        raise AmbientProgramError("unknown segment kind")
    if segment["kind"] == "hold":
        tile = _tile(segment.get("tile"))
        duration = segment.get("duration_ms")
        facing = segment.get("facing")
        if tile is None or isinstance(duration, bool) or not isinstance(duration, int) or not 0 < duration <= MAX_DURATION_MS:
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
        if view is None or isinstance(duration, bool) or not isinstance(duration, int) or not 0 < duration <= MAX_DURATION_MS:
            raise AmbientProgramError("invalid walk edge")
        views.append(view)
        total += duration
    if not 0 < total <= MAX_DURATION_MS:
        raise AmbientProgramError("invalid walk duration")
    return typed_waypoints[-1], total, typed_waypoints, views


def validate_ambient_program(program: Any, actor_ids: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    if isinstance(program, dict) and program.get("enabled") is False:
        if isinstance(program.get("revision"), int) and isinstance(program.get("reason"), str) and program["reason"] in {"legacy", "invalidated", "resting_only"}:
            return {"valid": True, "disabled": True}
        raise AmbientProgramError("invalid disabled ambient state")
    if not isinstance(program, dict) or program.get("enabled") is not True:
        raise AmbientProgramError("ambient state must be explicitly enabled or disabled")
    if not isinstance(program.get("revision"), int) or program["revision"] < 0:
        raise AmbientProgramError("invalid ambient revision")
    if not isinstance(program.get("epoch_ms"), (int, float)) or isinstance(program.get("epoch_ms"), bool):
        raise AmbientProgramError("invalid ambient epoch")
    cycle = program.get("cycle_ms")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle <= 0:
        raise AmbientProgramError("invalid ambient cycle")
    if isinstance(program.get("seed"), bool) or not isinstance(program.get("seed"), int):
        raise AmbientProgramError("invalid ambient seed")
    tracks = program.get("actors")
    if not isinstance(tracks, dict):
        raise AmbientProgramError("ambient actors are required")
    expected = set(actor_ids)
    if expected and set(tracks) != expected:
        raise AmbientProgramError("ambient actor tracks do not match the scene")
    walk_intervals: list[tuple[int, int]] = []
    for segments in tracks.values():
        if not isinstance(segments, list) or not segments:
            raise AmbientProgramError("actor needs an ambient track")
        elapsed = 0
        previous = None
        first = None
        for segment in segments:
            end, duration, _, _ = _validate_segment(segment, previous)
            if first is None:
                first = _tile(segment.get("tile")) if segment.get("kind") == "hold" else _tile(segment["waypoints"][0])
            if segment.get("kind") == "walk":
                walk_intervals.append((elapsed, elapsed + duration))
            elapsed += duration
            previous = end
        if elapsed != cycle:
            raise AmbientProgramError("actor track does not fill the cycle")
        if not _same_tile(first, previous):
            raise AmbientProgramError("ambient cycle wraps discontinuously")
    limit = program.get("max_walkers", 1)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
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
    home = home or {}
    tile_x = home.get("tile_x") if isinstance(home.get("tile_x"), int) else 0
    tile_y = home.get("tile_y") if isinstance(home.get("tile_y"), int) else 0
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
    track = program.get("actors", {}).get(actor_id)
    cycle = program.get("cycle_ms")
    epoch = program.get("epoch_ms")
    if not isinstance(track, list) or not isinstance(cycle, int) or cycle <= 0 or not isinstance(epoch, (int, float)) or not math.isfinite(time_ms):
        return _disabled_pose(home)
    remaining = ((time_ms - epoch) % cycle + cycle) % cycle
    for segment_index, segment in enumerate(track):
        duration = _duration(segment)
        if remaining < duration or segment_index == len(track) - 1:
            if segment.get("kind") == "hold":
                tile = _tile(segment.get("tile")) or (0, 0)
                return {
                    "mode": "hold",
                    "tile_x": tile[0],
                    "tile_y": tile[1],
                    "u": float(tile[0]),
                    "v": float(tile[1]),
                    "facing": segment.get("facing", "front_right"),
                    "segment_index": segment_index,
                    "edge_index": -1,
                    "progress": remaining / duration if duration else 0.0,
                }
            elapsed = remaining
            waypoints = [_tile(value) or (0, 0) for value in segment.get("waypoints", [])]
            for edge_index, edge_duration in enumerate(segment.get("edge_durations_ms", [])):
                if elapsed < edge_duration or edge_index == len(segment["edge_durations_ms"]) - 1:
                    first, second = waypoints[edge_index], waypoints[edge_index + 1]
                    progress = min(1.0, elapsed / edge_duration) if edge_duration else 1.0
                    return {
                        "mode": "walk",
                        "tile_x": second[0],
                        "tile_y": second[1],
                        "u": first[0] + (second[0] - first[0]) * progress,
                        "v": first[1] + (second[1] - first[1]) * progress,
                        "facing": VIEW_BY_DELTA[(second[0] - first[0], second[1] - first[1])],
                        "segment_index": segment_index,
                        "edge_index": edge_index,
                        "progress": progress,
                    }
                elapsed -= edge_duration
        remaining -= duration
    return _disabled_pose(home)
