"""Commons profile APIs plus an isolated legacy movie protocol."""
import os
import tarfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from commons_account.routes import current_user
from commons_roles import user_role
from .package import Package
from .store import Store
from .package_store import PackageStore, MAX_UPLOAD
from .origin import player_origin
from . import controls, wire
from .rooms import router as rooms_router

router = APIRouter()
router.include_router(rooms_router)

def store(request: Request) -> Store:
    # Use the existing uncached Commons client, including its normal server credentials.
    return Store(request.app.state.mcp_supabase)

def package_store(request: Request) -> PackageStore:
    return request.app.state.arcade_packages

def package(request: Request) -> Package:
    # A local package is still supported for offline development.
    path = os.environ.get("ARCADE_PACKAGE_PATH")
    if path and (Path(path) / "manifest.json").is_file():
        return load_package(path)
    bundle = package_store(request).current()
    if bundle is None:
        raise HTTPException(503, "A Commons admin needs to install the game package")
    return bundle

@lru_cache(maxsize=4)
def load_package(path: str) -> Package:
    return Package(Path(path))

class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    das_ms: Literal[280, 200, 150, 133, 120] = 200
    arr_ms: Literal[50, 35, 17, 7, 0] = 35
    # Per game id: {"keys": {action: code}, "pad": {action: button}}; checked by controls.validate.
    controls: dict[str, dict] = Field(default_factory=dict)
    sound: bool = True
    frame_rate: Literal[0, 60, 100, 144, 240] = 60
    opponent_level: int = Field(default=0, ge=0, le=21)

@router.get("/profile")
def get_profile(user=Depends(current_user), state=Depends(store)):
    return state.profile(str(user.id))["settings"]

@router.put("/profile")
def save_profile(payload: Settings, user=Depends(current_user), state=Depends(store)):
    problem = controls.validate(payload.controls)
    if problem:
        raise HTTPException(400, problem)
    state.save_profile(str(user.id), payload.model_dump())
    return payload

@router.get("/controls")
def get_controls(user=Depends(current_user), state=Depends(store)):
    profile = state.profile(str(user.id))
    return controls.describe(controls_for(profile["legacy_settings"]),
                             controls.binding_for(profile["settings"], controls.SPRINT))

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
    profile = state.profile(str(user.id))
    settings = profile["settings"]
    frame_rate = settings["frame_rate"]
    if frame_rate not in bundle.manifest.get("frame_rates", [0]):
        raise HTTPException(409, "Install the timing-corrected game package for this frame rate")
    trusted = getattr(bundle, "trusted", False)
    origin = player_origin()
    if not trusted and not origin:
        raise HTTPException(503, "Untrusted games need the separate player origin")
    session = state.launch(str(user.id))
    return {"id": session["id"], "frame_rate": frame_rate, "trusted": trusted,
            **({"frame": origin + "/arcade/frame"} if origin else {}), "session": wire.encrypt(session["token"], bundle.manifest["wire_key"].encode()),
            "entry": bundle.manifest["entry"], "origins": bundle.manifest["origins"],
            "callbacks": bundle.manifest["callbacks"],
            "input": controls.resolve(controls_for(profile["legacy_settings"]),
                                      controls.binding_for(settings, controls.SPRINT))}

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
    return await run_in_threadpool(game_reply, bytes(body), state, bundle)

def game_reply(body: bytes, state: Store, bundle: Package) -> Response:
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
    headers = {"Cache-Control": "no-store"}
    if root.tag == "CreateSprintGameRecordRQ":
        headers["X-Arcade-Run"] = "finished"
    return Response(reply, media_type="text/xml", headers=headers)

def frame_parents(request: Request) -> list[str]:
    """Commons pages allowed to embed the frame and exchange messages with it."""
    origins = ["http://localhost:8080", "http://127.0.0.1:8080"]
    origins += [value.strip().rstrip("/") for value in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if value.strip()]
    # On the API origin the frame is embedded by itself in legacy setups; the
    # player origin is never its own parent.
    return origins if player_origin() else [str(request.base_url).rstrip("/"), *origins]

@router.get("/frame")
def frame(request: Request):
    origins = frame_parents(request)
    policy = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
              "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
              "object-src 'none'; base-uri 'none'; form-action 'none'; "
              "frame-ancestors " + " ".join(origins))
    return FileResponse(Path(__file__).with_name("frame.html"), headers={
        "Content-Security-Policy": policy, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

@router.get("/frame.js")
def frame_script(request: Request):
    import json
    script = Path(__file__).with_name("frame.js").read_text().replace("__PARENT_ORIGINS__", json.dumps(frame_parents(request)))
    return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-store"})

@router.get("/frame.css")
def frame_style():
    return FileResponse(Path(__file__).with_name("frame.css"), media_type="text/css")

def require_package_admin(request: Request, user=Depends(current_user)):
    if not getattr(user, "email_confirmed_at", None) or user_role(request.app.state.mcp_supabase, user.id) != "admin":
        raise HTTPException(403, "Only a Commons admin can install game packages")
    return user

@router.get("/package")
def package_status(request: Request, user=Depends(current_user)):
    local = os.environ.get("ARCADE_PACKAGE_PATH")
    return {"installed": bool(local and (Path(local) / "manifest.json").is_file()) or package_store(request).installed(),
            "can_install": user_role(request.app.state.mcp_supabase, user.id) == "admin"}

@router.post("/package")
async def install_package(request: Request, user=Depends(require_package_admin)):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "Game package exceeds 40 MB")
    try:
        await run_in_threadpool(package_store(request).install, bytes(content), str(user.id))
    except (ValueError, tarfile.TarError, KeyError, TypeError):
        raise HTTPException(400, "Invalid or damaged game package") from None
    return {"installed": True}
