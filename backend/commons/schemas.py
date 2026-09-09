"""API models for the shared Cozy Commons scene."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CommonsSceneOut(BaseModel):
    id: str
    layout_version: int
    version: int
    state: dict[str, Any]
    updated_at: datetime
    server_time_ms: int


class CommonsSceneCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    client_command_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)
    kind: Literal["move_object", "walk_actor", "set_object_state", "rotate_object"]
    payload: dict[str, Any]


class CommonsSceneCommandReceipt(BaseModel):
    scene_id: str
    client_command_id: str
    accepted_version: int
    version: int
    state: dict[str, Any]
    replayed: bool = False
