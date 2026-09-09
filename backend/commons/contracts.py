"""Load the versioned Commons semantic contract shared with the frontend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CONTRACT_RELATIVE_PATH = Path("shared/commons/scene-contract-v1.json")
_FALLBACK_CONTRACT: dict[str, Any] = {
    "contract_version": 1,
    "catalog_version": "commons-v2",
    "max_schema_version": 7,
    "world": {
        "columns": 16,
        "rows": 16,
        "width": 512,
        "height": 512,
        "tile_width": 32,
        "tile_height": 20,
        "origin_x": 256,
        "origin_y": 180,
        "source_scale": 3,
    },
    "actor_views": {
        "1,0": "front_right",
        "0,1": "front_left",
        "-1,0": "back_left",
        "0,-1": "back_right",
    },
    "ambient": {"cycle_ms": 180000, "max_walkers": 1, "default_edge_duration_ms": 1000},
}


def _contract_paths() -> tuple[Path, ...]:
    module_path = Path(__file__).resolve()
    return (
        module_path.parents[2] / _CONTRACT_RELATIVE_PATH,
        module_path.parents[1] / _CONTRACT_RELATIVE_PATH,
    )


def _load_contract() -> dict[str, Any]:
    for path in _contract_paths():
        try:
            with path.open(encoding="utf-8") as handle:
                candidate = json.load(handle)
            if isinstance(candidate, dict) and candidate.get("contract_version") == 1:
                return candidate
        except (OSError, json.JSONDecodeError):
            continue
    return _FALLBACK_CONTRACT


SCENE_CONTRACT = _load_contract()


def contract_path() -> Path | None:
    """Return the deployed shared contract path, or ``None`` for fallback."""

    for path in _contract_paths():
        if path.is_file():
            return path
    return None
