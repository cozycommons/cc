"""Commons profile APIs plus an isolated legacy movie protocol."""
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from commons_account.routes import current_user
from .package import Package
from .store import Store
from . import wire

router = APIRouter()

@lru_cache(maxsize=4)
def open_store(path: str) -> Store:
    return Store(Path(path))

def store() -> Store:
    path = os.environ.get("ARCADE_STATE_PATH")
    if not path:
        raise HTTPException(503, "Arcade storage is not configured")
    return open_store(path)

def package() -> Package:
    path = os.environ.get("ARCADE_PACKAGE_PATH")
    if not path or not (Path(path) / "manifest.json").is_file():
        raise HTTPException(503, "The game package is not installed")
    return load_package(path)

@lru_cache(maxsize=4)
def load_package(path: str) -> Package:
    return Package(Path(path))

class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    das_ms: Literal[280, 200, 150, 133, 120] = 200
    arr_ms: Literal[50, 35, 17, 7, 0] = 35
    keys: dict[str, str] = Field(default_factory=lambda: {"left": "KeyJ", "right": "KeyL", "soft": "KeyK"})
    sound: bool = True
    frame_rate: Literal[0, 60, 100, 144, 240] = 60
    opponent_level: int = Field(default=0, ge=0, le=21)

@router.get("/profile")
def get_profile(user=Depends(current_user), state=Depends(store)):
    return state.profile(str(user.id))["settings"]

@router.put("/profile")
def save_profile(payload: Settings, user=Depends(current_user), state=Depends(store)):
    actions = {"left", "right", "soft", "hard", "cw", "ccw", "hold"}
    if (not payload.keys.keys() <= actions or len(set(payload.keys.values())) != len(payload.keys)
            or any(not key.isascii() or not key.isalnum() or len(key) > 24 for key in payload.keys.values())):
        raise HTTPException(400, "Choose a distinct keyboard key for each action")
    state.save_profile(str(user.id), payload.model_dump())
    return payload

@router.get("/runs")
def get_runs(user=Depends(current_user), state=Depends(store)):
    return state.runs(str(user.id))

def controls_for(xml: str) -> dict[str, int]:
    root = wire.parse_xml(xml)
    actions = ["left", "right", "hard", "soft", "cw", "ccw", "hold"]
    defaults = [37, 39, 32, 40, 88, 90, 67]
    if root.findtext("IsCustomControls") == "true":
        saved = root.findtext("Controls", "").split(",")
        if len(saved) >= 8 and all(value.strip().isdigit() for value in saved):
            defaults = [int(value) for value in saved[:7]]
    return dict(zip(actions, defaults))

@router.post("/sessions")
def launch(user=Depends(current_user), state=Depends(store), bundle=Depends(package)):
    settings = state.profile(str(user.id))["settings"]
    frame_rate = settings["frame_rate"]
    if frame_rate not in bundle.manifest.get("frame_rates", [0]):
        raise HTTPException(409, "Install the timing-corrected game package for this frame rate")
    session = state.launch(str(user.id))
    return {"id": session["id"], "frame_rate": frame_rate, "session": wire.encrypt(session["token"], bundle.manifest["wire_key"].encode()),
            "entry": bundle.manifest["entry"], "origins": bundle.manifest["origins"],
            "callbacks": bundle.manifest["callbacks"],
            "controls": controls_for(state.profile(str(user.id))["legacy_settings"])}

@router.get("/player/{name}")
def player_file(name: str, bundle=Depends(package)):
    path = (bundle.root / "player" / name).resolve()
    if not path.is_relative_to(bundle.root / "player") or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

@router.get("/assets/{key:path}")
def asset(key: str, bundle=Depends(package)):
    found = bundle.file(key)
    if not found:
        raise HTTPException(404, "Asset absent from the installed package")
    path, content_type = found
    return FileResponse(path, media_type=content_type, headers={"X-Content-Type-Options": "nosniff"})

@router.post("/compat/api")
async def game_api(request: Request, state=Depends(store), bundle=Depends(package)):
    # Bound before buffering. Bodies contain game-session capabilities and are never logged.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4 * 1024 * 1024:
            raise HTTPException(413)
    key = bundle.manifest["wire_key"].encode()
    try:
        root = wire.decode(bytes(body), key)
        carried = unquote(root.findtext("SessionId", ""))
        try:
            token = wire.decrypt(carried, key)
        except (ValueError, UnicodeError):
            token = carried
        session = state.session(token)
        if not session:
            raise HTTPException(401, "Game session expired")
        reply = wire.handle(root, session, state, key)
    except (ValueError, UnicodeError, IndexError, wire.ET.ParseError):
        raise HTTPException(400, "Invalid game request") from None
    return Response(reply, media_type="text/xml", headers={"Cache-Control": "no-store"})

@router.get("/frame")
def frame(request: Request):
    origins = [str(request.base_url).rstrip("/"), "http://localhost:8080", "http://127.0.0.1:8080"]
    origins += [value.strip().rstrip("/") for value in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if value.strip()]
    policy = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
              "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
              "object-src 'none'; base-uri 'none'; form-action 'none'; "
              "frame-ancestors " + " ".join(origins))
    return FileResponse(Path(__file__).with_name("frame.html"), headers={
        "Content-Security-Policy": policy, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

@router.get("/frame.js")
def frame_script(request: Request):
    import json
    origins = [str(request.base_url).rstrip("/"), "http://localhost:8080", "http://127.0.0.1:8080"]
    origins += [value.strip().rstrip("/") for value in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if value.strip()]
    script = Path(__file__).with_name("frame.js").read_text().replace("__PARENT_ORIGINS__", json.dumps(origins))
    return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-store"})

@router.get("/frame.css")
def frame_style():
    return FileResponse(Path(__file__).with_name("frame.css"), media_type="text/css")
