"""Public API for the shared Cozy Commons home scene."""

from __future__ import annotations

import re
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request

from commons.schemas import CommonsSceneCommandReceipt, CommonsSceneCommandRequest, CommonsSceneOut
from commons.scene_service import (
    SceneCommandError,
    SceneConflictError,
    SceneStoreError,
    commit_scene_command,
    read_scene,
)

router = APIRouter()
_ACTOR_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _client(request: Request):
    client = getattr(request.app.state, "commons_supabase", None)
    return client if client is not None else request.app.state.supabase_admin


def _actor_key(value: str | None) -> str:
    key = (value or "anonymous").strip()
    if not _ACTOR_KEY.fullmatch(key):
        raise HTTPException(status_code=422, detail={"code": "commons.invalid_client_id"})
    return key


@router.get("/scene", response_model=CommonsSceneOut)
def get_scene(request: Request) -> CommonsSceneOut:
    try:
        row = read_scene(_client(request))
        return CommonsSceneOut.model_validate({**row, "server_time_ms": int(time.time() * 1000)})
    except SceneStoreError as error:
        raise HTTPException(status_code=503, detail={"code": str(error)}) from error


@router.post("/scene/commands", response_model=CommonsSceneCommandReceipt)
def post_scene_command(
    request: Request,
    payload: CommonsSceneCommandRequest,
    client_id: Annotated[str | None, Header(alias="X-Scene-Client-Id")] = None,
) -> CommonsSceneCommandReceipt:
    try:
        result = commit_scene_command(_client(request), _actor_key(client_id), payload)
        return CommonsSceneCommandReceipt.model_validate(result)
    except SceneCommandError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": f"commons.{error.code}", "message": error.message},
        ) from error
    except SceneConflictError as error:
        detail = {"code": f"commons.{error.code}"}
        if error.current_version is not None:
            detail["current_version"] = error.current_version
        raise HTTPException(status_code=409, detail=detail) from error
    except SceneStoreError as error:
        raise HTTPException(status_code=503, detail={"code": str(error)}) from error
