"""Suggest and confirm public team links using Cozy's existing Dice identity."""

import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from postgrest.exceptions import APIError
from pydantic import HttpUrl, ValidationError

from dice.routes import AuthedUser, require_authenticated_user
from .public_predictions import PublicModel, PublicSnapshotV2, SeasonYear

router = APIRouter()


class ClaimBody(PublicModel):
    season: SeasonYear
    team_id: int


# Until uploads are configured, the public page reads an interim snapshot host; claims
# use the same published (already public) snapshot so linking works in the meantime.
FALLBACK_URL = os.getenv(
    "ESPN_PUBLIC_PREDICTIONS_FALLBACK_URL",
    "https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/fantasy-latest.json",
)
_fallback_cache = {"at": None, "payload": None}  # None: never fetched


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECTS = urllib.request.build_opener(_RefuseRedirect())


def _fallback_snapshot():
    if _fallback_cache["at"] is not None and time.monotonic() - _fallback_cache["at"] < 300:
        return _fallback_cache["payload"]
    payload = None
    if FALLBACK_URL:
        try:
            with _NO_REDIRECTS.open(FALLBACK_URL, timeout=5) as response:
                body = response.read(256 * 1024 + 1)
            if len(body) > 256 * 1024:
                raise ValueError("fallback snapshot too large")
            payload = PublicSnapshotV2.model_validate_json(body).model_dump(mode="json", exclude_unset=True)
        except (OSError, urllib.error.URLError, ValidationError, ValueError):
            payload = None
    _fallback_cache.update(at=time.monotonic(), payload=payload)
    return payload


def _latest_snapshot(db, season=None):
    stored = _stored_snapshot(db, season)
    if stored is not None and stored.get("teams"):  # v1 rows carry no team list
        return stored
    fallback = _fallback_snapshot()
    if fallback is not None and (season is None or _season(fallback) == season):
        return fallback
    return None


def _stored_snapshot(db, season=None):
    query = db.table("espn_public_predictions").select("payload")
    if season is not None:
        query = query.or_(
            f"payload->>season_year.eq.{season},and(payload->>season_year.is.null,"
            f"payload->>captured_at.gte.{season - 1}-07-01,"
            f"payload->>captured_at.lt.{season}-07-01)"
        )
    rows = query.order("received_at", desc=True).limit(1).execute().data
    return rows[0]["payload"] if rows else None


def _season(snapshot):
    if snapshot is None:
        return None
    if type(snapshot.get("season_year")) is int:
        return snapshot["season_year"]
    # NBA seasons end the next calendar year after July. Keep legacy snapshots
    # without an explicit season_year available for claims.
    captured = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
    return captured.year + (captured.month >= 7)


def _claims(db, season):
    return db.table("espn_team_claims").select("id,team_id,user_id").eq(
        "season", season
    ).execute().data


def _profile(db, user_id):
    rows = db.table("dice_profiles").select("display_name").eq(
        "user_id", user_id
    ).limit(1).execute().data
    return rows[0] if rows else None


def _tokens(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        char if char.isalnum() else " "
        for char in decomposed if not unicodedata.combining(char)
    ).split()


def _similarity(name, candidate):
    left, right = _tokens(name), _tokens(candidate)
    if not left or not right:
        return 0.0
    score = SequenceMatcher(None, " ".join(sorted(left)), " ".join(sorted(right))).ratio()
    if left[0] == right[0]:
        score = max(score, 0.95)
    return score


# Self-service links need a reasonable name match; Dice admins can link any team.
MATCH_THRESHOLD = 0.5


def _user_names(profile, auth):
    names = [profile["display_name"]] if profile else []
    names.extend(value for key in ("full_name", "name", "given_name")
                 if isinstance(value := auth.metadata.get(key), str))
    return names


def _team_score(names, team):
    return max((max(_similarity(name, team.get("manager") or ""),
                    0.6 * _similarity(name, team["name"])) for name in names), default=0)


@router.get("/public/claims")
def public_claims(request: Request, response: Response, season: int | None = None):
    db = request.app.state.supabase
    snapshot = _latest_snapshot(db)
    latest_season = _season(snapshot)
    if season != latest_season and (
        season is None or not 2000 <= season <= 2100 or _latest_snapshot(db, season) is None
    ):
        season = latest_season
    response.headers["Cache-Control"] = "public, max-age=60"
    if season is None:
        return []
    claims = _claims(db, season)
    if not claims:
        return []
    profiles = db.table("dice_profiles").select("user_id,display_name,avatar_url").in_(
        "user_id", [claim["user_id"] for claim in claims]
    ).execute().data
    by_user = {profile["user_id"]: profile for profile in profiles}
    result = []
    for claim in sorted(claims, key=lambda row: row["team_id"]):
        profile = by_user.get(claim["user_id"])
        if profile is None:
            continue
        avatar = profile.get("avatar_url")
        try:
            if not avatar or HttpUrl(avatar).scheme != "https":
                avatar = None
        except ValidationError:
            avatar = None
        result.append({
            "team_id": claim["team_id"], "display_name": profile["display_name"],
            "avatar_url": avatar,
        })
    return result


@router.get("/claims/suggestions")
def suggestions(request: Request, auth: AuthedUser = Depends(require_authenticated_user)):
    db = request.app.state.supabase
    profile = _profile(db, auth.user_id)
    names = _user_names(profile, auth)
    snapshot = _latest_snapshot(db)
    season = _season(snapshot)
    claims = _claims(db, season) if season is not None else []
    by_team = {claim["team_id"]: claim["user_id"] for claim in claims}
    mine = next(({"team_id": claim["team_id"]} for claim in claims
                 if claim["user_id"] == auth.user_id), None)
    teams = []
    for team in (snapshot or {}).get("teams", []):
        score = _team_score(names, team)
        teams.append({
            "team_id": team["id"], "name": team["name"], "manager": team.get("manager"),
            "score": round(score, 4), "claimed": team["id"] in by_team,
            "mine": by_team.get(team["id"]) == auth.user_id,
            "can_claim": auth.is_admin or score >= MATCH_THRESHOLD,
        })
    teams.sort(key=lambda team: (-team["score"], team["team_id"]))
    return {"season": season, "has_profile": profile is not None, "mine": mine, "teams": teams}


@router.post("/claims")
def claim_team(body: ClaimBody, request: Request,
               auth: AuthedUser = Depends(require_authenticated_user)):
    db = request.app.state.supabase
    snapshot = _latest_snapshot(db)
    if _season(snapshot) != body.season:
        snapshot = _latest_snapshot(db, body.season)
    team = next((t for t in (snapshot or {}).get("teams", []) if t["id"] == body.team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail="team_not_found")
    profile = _profile(db, auth.user_id)
    if profile is None:
        raise HTTPException(status_code=409, detail="profile_required")
    if not auth.is_admin and _team_score(_user_names(profile, auth), team) < MATCH_THRESHOLD:
        raise HTTPException(status_code=403, detail="name_mismatch")
    try:
        db.rpc("espn_claim_team", {
            "p_season": body.season, "p_team_id": body.team_id, "p_user_id": auth.user_id,
        }).execute()
    except APIError as error:
        if error.code == "23505":
            raise HTTPException(status_code=409, detail="team_claimed") from error
        raise
    return {"season": body.season, "team_id": body.team_id}


@router.delete("/claims/{season}/{team_id}")
def delete_claim(season: int, team_id: int, request: Request,
                 auth: AuthedUser = Depends(require_authenticated_user)):
    db = request.app.state.supabase
    rows = db.table("espn_team_claims").select("id,user_id").eq(
        "season", season
    ).eq("team_id", team_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="claim_not_found")
    claim = rows[0]
    if claim["user_id"] != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="claim_owner_required")
    db.table("espn_team_claims").delete().eq("id", claim["id"]).execute()
    return {"season": season, "team_id": team_id}


# Server-only; never part of a snapshot or a public response. Unset hides league links.
LEAGUE_ID_ENV = "ESPN_FANTASY_LEAGUE_ID"
ESPN_FANTASY = "https://fantasy.espn.com/basketball"


def _league_id():
    value = os.getenv(LEAGUE_ID_ENV, "").strip()
    return value if re.fullmatch(r"\d{1,12}", value) else None


def league_links(league_id, season, team_id, matchup_id, matchups):
    """ESPN URLs for one claimed team; matchups are (home, away) team ID pairs."""
    def url(path, **params):
        return f"{ESPN_FANTASY}/{path}?{urlencode({'leagueId': league_id, **params})}"

    team = {"teamId": team_id, "seasonId": season}
    return {
        "team": url("team", **team),
        "lineup": url("team", **team, statSplit="singleScoringPeriod"),
        "free_agents": url("players/add", **team),
        "matchups": {
            str(home): url("boxscore", matchupPeriodId=matchup_id, seasonId=season, teamId=home)
            for home, _ in matchups
        } if matchup_id is not None else {},
    }


@router.get("/claims/links")
def claim_links(request: Request, response: Response,
                auth: AuthedUser = Depends(require_authenticated_user)):
    response.headers["Cache-Control"] = "private, no-store"
    db = request.app.state.supabase
    snapshot = _latest_snapshot(db)
    season = _season(snapshot)
    mine = next((claim for claim in (_claims(db, season) if season is not None else [])
                 if claim["user_id"] == auth.user_id), None)
    if mine is None:
        raise HTTPException(status_code=403, detail="claim_required")
    league_id = _league_id()
    if league_id is None:
        raise HTTPException(status_code=404, detail="league_links_unavailable")
    pairs = [(m["home"], m["away"]) for m in snapshot.get("matchups", [])
             if isinstance(m.get("home"), int) and isinstance(m.get("away"), int)]
    matchup_id = (snapshot.get("matchup") or {}).get("id")
    return {"season": season, "team_id": mine["team_id"],
            **league_links(league_id, season, mine["team_id"], matchup_id, pairs)}
