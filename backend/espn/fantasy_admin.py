"""Service-only, per-season fantasy settings using Cozy administrator identity."""
import json
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from postgrest.exceptions import APIError
from starlette.concurrency import run_in_threadpool

from dice.routes import AuthedUser, require_authenticated_user

router = APIRouter()
_CACHE_SECONDS = 30


def require_admin(auth: AuthedUser = Depends(require_authenticated_user)):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return auth


def _season(season):
    if not 2000 <= season <= 2100:
        raise HTTPException(status_code=422, detail="invalid_season")


def _read(db, season):
    rows = db.table("fantasy_leagues").select("espn_league_id").eq(
        "season", season
    ).limit(1).execute().data
    return rows[0]["espn_league_id"] if rows else None


def league_id_for_season(request, season):
    """Cache only on this application's state; never consult an environment ID."""
    _season(season)
    cache = getattr(request.app.state, "fantasy_leagues_cache", None)
    if cache is None:
        cache = request.app.state.fantasy_leagues_cache = {}
    now = time.monotonic()
    cached = cache.get(season)
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        value = _read(request.app.state.supabase, season)
    except APIError:
        raise HTTPException(status_code=503, detail="league_settings_unavailable") from None
    cache[season] = (now, value)
    return value


@router.get("/admin")
def admin_status(response: Response, auth=Depends(require_admin)):
    response.headers["Cache-Control"] = "private, no-store"
    return {"is_admin": True}


@router.get("/admin/leagues/{season}")
def get_league(season: int, request: Request, response: Response,
               auth=Depends(require_admin)):
    response.headers["Cache-Control"] = "private, no-store"
    _season(season)
    try:
        value = _read(request.app.state.supabase, season)
    except APIError:
        raise HTTPException(status_code=503, detail="league_settings_unavailable") from None
    return {"season": season, "espn_league_id": value}


@router.put("/admin/leagues/{season}")
async def put_league(season: int, request: Request, response: Response,
                     auth=Depends(require_admin)):
    response.headers["Cache-Control"] = "private, no-store"
    _season(season)
    # Parse after authorization and return fixed errors: validation must not echo IDs.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024:
            raise HTTPException(status_code=413, detail="settings_too_large")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(status_code=422, detail="invalid_league_id") from None
    value = body.get("espn_league_id") if isinstance(body, dict) else None
    if (not isinstance(body, dict) or set(body) != {"espn_league_id"}
            or not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}", value)):
        raise HTTPException(status_code=422, detail="invalid_league_id")
    try:
        query = request.app.state.supabase.table("fantasy_leagues").upsert({
            "season": season, "espn_league_id": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": auth.user_id,
        }, on_conflict="season")
        await run_in_threadpool(query.execute)
    except APIError:
        raise HTTPException(status_code=503, detail="league_settings_unavailable") from None
    # Invalidating avoids caching an ID that lost a concurrent write.
    getattr(request.app.state, "fantasy_leagues_cache", {}).pop(season, None)
    return {"season": season, "saved": True}
