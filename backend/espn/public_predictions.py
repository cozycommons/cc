"""Allowlisted public league estimates, uploaded without contacting ESPN."""

import base64
import binascii
import hmac
import hashlib
import json
import re
from collections import OrderedDict
import os
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError, field_validator,
    model_validator,
)

MAX_BODY_BYTES = 256 * 1024
Number = Annotated[float, Field(allow_inf_nan=False)]
Chance = Annotated[Number, Field(ge=0, le=100)]
MatchupId = Annotated[int, Field(ge=-(2**63), le=2**63 - 1)]
Games = Annotated[int, Field(ge=0, le=20)]
NonnegativeInt = Annotated[int, Field(ge=0)]
SeasonYear = Annotated[int, Field(ge=2000, le=2100)]
SeasonMode = Literal["projections", "balanced", "hot"]
MAX_LOGO_BYTES = 24 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CLOCK_SKEW = timedelta(minutes=10)


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PublicTeam(PublicModel):
    name: str = Field(max_length=60)


class PublicMatchup(PublicModel):
    id: MatchupId
    ends: date


class PublicDay(PublicModel):
    date: date
    state: Literal["final", "live", "projected"]
    actual: tuple[Number | None, Number | None] | None
    # Finished days can predate the first saved forecast; later days must be projected.
    expected: tuple[Number | None, Number | None]
    games: tuple[Games | None, Games | None]

    @model_validator(mode="after")
    def projected_days_have_numbers(self):
        if self.state != "final" and None in (*self.expected, *self.games):
            raise ValueError("live and projected days need expected points and games")
        return self


class PublicOddsPoint(PublicModel):
    date: date
    chance: Chance
    at: AwareDatetime | None = None  # capture time; present when points are intraday

    @field_validator("at", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO string")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


class PublicPrediction(PublicModel):
    home: PublicTeam
    away: PublicTeam
    scores: tuple[Number, Number]
    projected_totals: tuple[Number, Number]
    chance: Chance
    range: tuple[Number, Number]
    margin_80: tuple[Number, Number]
    days: list[PublicDay] = Field(max_length=14)
    odds_history: list[PublicOddsPoint] = Field(max_length=200)

    @model_validator(mode="after")
    def bounds_are_ordered(self):
        if self.range[0] > self.range[1] or self.margin_80[0] > self.margin_80[1]:
            raise ValueError("range and margin_80 must be [low, high]")
        dates = [day.date for day in self.days]
        if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
            raise ValueError("days must have unique, increasing dates")
        return self


class UnavailablePrediction(PublicModel):
    home: PublicTeam
    away: PublicTeam
    unavailable: Literal[True]

    @field_validator("unavailable", mode="before")
    @classmethod
    def only_true(cls, value):
        if value is not True:
            raise ValueError("unavailable must be true")
        return value


class PublicSnapshot(PublicModel):
    version: Literal["public-v1"]
    generated_at: AwareDatetime
    captured_at: AwareDatetime
    names: Literal["real", "abbrev", "initials"] = "abbrev"
    matchup: PublicMatchup
    label: str = Field(max_length=120)
    matchups: list[PublicPrediction | UnavailablePrediction] = Field(max_length=20)

    @field_validator("generated_at", "captured_at", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        # Pydantic also accepts epoch seconds encoded as strings by default.
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO string")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @model_validator(mode="after")
    def not_from_the_future(self):
        # Rows are append-only; a future-dated upload must never be accepted.
        limit = datetime.now(timezone.utc) + MAX_CLOCK_SKEW
        if self.generated_at > limit or self.captured_at > limit:
            raise ValueError("snapshot timestamps are in the future")
        return self


class PublicTeamV2(PublicModel):
    id: int
    name: str = Field(max_length=60)
    abbrev: str = Field(max_length=12)
    logo: str | None
    manager: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z][A-Za-z '\-.]*$")

    @field_validator("logo")
    @classmethod
    def public_logo(cls, value):
        if value is None:
            return value
        prefix = "data:image/png;base64,"
        if value.startswith(prefix):
            payload = value[len(prefix):]
            if len(payload) > 4 * ((MAX_LOGO_BYTES + 2) // 3):
                raise ValueError("logo is too large")
            try:
                decoded = base64.b64decode(payload, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("logo must contain base64 PNG data")
            if len(decoded) > MAX_LOGO_BYTES or not decoded.startswith(PNG_SIGNATURE):
                raise ValueError("logo must be a PNG of at most 24 KiB")
        else:
            if len(value) > 300:
                raise ValueError("logo URL is too long")
            url = HttpUrl(value)
            if url.scheme != "https" or url.host != "g.espncdn.com":
                raise ValueError("logo URL must use ESPN's HTTPS CDN")
        return value


class DraftAcquired(PublicModel):
    how: Literal["draft"]
    round: Annotated[int, Field(ge=1, le=40)]
    pick: Annotated[int, Field(ge=1, le=600)]


class OtherAcquired(PublicModel):
    how: Literal["add", "trade"]


class PublicPlayer(PublicModel):
    id: NonnegativeInt
    name: str = Field(max_length=60)
    points: Number | None
    expected: Number | None = None
    acquired: Annotated[DraftAcquired | OtherAcquired, Field(discriminator="how")] | None = None


PlayerSide = Annotated[list[PublicPlayer], Field(max_length=15)]


class PublicDayV2(PublicDay):
    players: tuple[PlayerSide, PlayerSide] | None = None

    @model_validator(mode="after")
    def observed_players_only(self):
        if self.state == "projected" and self.players is not None:
            raise ValueError("projected days cannot include players")
        return self


class PublicPredictionV2(PublicPrediction):
    home: int
    away: int
    days: list[PublicDayV2] = Field(max_length=14)


class UnavailablePredictionV2(UnavailablePrediction):
    home: int
    away: int


class PublicSeasonTeam(PublicModel):
    team: int
    record: tuple[NonnegativeInt, NonnegativeInt, NonnegativeInt]
    expected_wins: Number = Field(ge=0)
    playoff_pct: Chance
    title_pct: Chance
    place_pct: list[Chance] = Field(max_length=20)

    @field_validator("place_pct")
    @classmethod
    def total_probability(cls, value):
        if abs(sum(value) - 100) > 0.5:
            raise ValueError("place percentages must sum to 100 within 0.5")
        return value


class PublicSeasonPoint(PublicModel):
    date: date
    playoff_pct: Chance


class PublicSeason(PublicModel):
    weeks_remaining: NonnegativeInt
    playoff_teams: int = Field(ge=1)
    trials: int = Field(ge=1, le=100000)
    modes: dict[SeasonMode, Annotated[list[PublicSeasonTeam], Field(max_length=20)]]
    history: dict[SeasonMode, dict[str, Annotated[list[PublicSeasonPoint], Field(max_length=60)]]]
    form_active: bool

    @model_validator(mode="after")
    def history_dates_increase(self):
        for teams in self.history.values():
            for points in teams.values():
                dates = [point.date for point in points]
                if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
                    raise ValueError("season history must have unique, increasing dates")
        return self


class PublicSnapshotV2(PublicSnapshot):
    version: Literal["public-v2"]
    teams: list[PublicTeamV2] = Field(max_length=20)
    matchups: list[PublicPredictionV2 | UnavailablePredictionV2] = Field(max_length=20)
    season: PublicSeason | None = None
    season_year: SeasonYear | None = None

    @model_validator(mode="after")
    def known_teams(self):
        team_ids = {team.id for team in self.teams}
        if len(team_ids) != len(self.teams):
            raise ValueError("team ids must be unique")
        matched = set()
        for matchup in self.matchups:
            for team in (matchup.home, matchup.away):
                if team not in team_ids or team in matched:
                    raise ValueError("matchup teams must be known and unique")
                matched.add(team)
        if self.season is not None:
            if self.season.playoff_teams > len(team_ids):
                raise ValueError("playoff teams cannot exceed the number of teams")
            for standings in self.season.modes.values():
                seen = set()
                for standing in standings:
                    if standing.team not in team_ids or standing.team in seen:
                        raise ValueError("season teams must be known and unique")
                    seen.add(standing.team)
                    if len(standing.place_pct) != len(team_ids):
                        raise ValueError("place percentages must cover every place")
            known_keys = {str(team) for team in team_ids}
            for history in self.season.history.values():
                if not history.keys() <= known_keys:
                    raise ValueError("season history teams must be known")
        return self


Snapshot = Annotated[PublicSnapshot | PublicSnapshotV2, Field(discriminator="version")]
_snapshot_adapter = TypeAdapter(Snapshot)


router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _upload_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    token = os.getenv("ESPN_PUBLIC_PREDICTIONS_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="public predictions upload disabled")
    if not credentials or not hmac.compare_digest(
        credentials.credentials.encode("utf-8"), token.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid bearer token")


async def _read_snapshot(request: Request, _auth=Depends(_upload_auth)) -> Snapshot:
    # Bound the actual stream before parsing, including chunked/undeclared bodies.
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="snapshot exceeds 256 KiB")
        raw.extend(chunk)
    try:
        return _snapshot_adapter.validate_json(raw)
    except ValidationError:
        # Do not echo rejected private fields or non-finite JSON values in errors.
        raise HTTPException(status_code=422, detail="invalid public snapshot")


@router.post("/public/predictions")
def upload(request: Request, snapshot: Snapshot = Depends(_read_snapshot)):
    generated_at = snapshot.generated_at.astimezone(timezone.utc).isoformat()
    result = request.app.state.supabase.table("espn_public_predictions").upsert(
        {
            "matchup_id": snapshot.matchup.id,
            "generated_at": generated_at,
            "payload": snapshot.model_dump(mode="json", exclude_unset=True),
        },
        on_conflict="matchup_id,generated_at",
        ignore_duplicates=True,
    ).execute()
    return {
        "stored": bool(result.data),
        "matchup_id": snapshot.matchup.id,
        "generated_at": generated_at,
    }


# Content-addressed logos are separate from score data and bounded per worker.
_logos = OrderedDict()


def _public_payload(request):
    result = request.app.state.supabase.table("espn_public_predictions").select(
        "payload"
    ).order("received_at", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]["payload"]
    # The existing public fallback is bounded, validated and cached.
    from .team_claims import _fallback_snapshot
    return _fallback_snapshot()


def _external_logos(payload):
    if not payload.get("teams"):
        return payload
    teams = []
    for team in payload["teams"]:
        logo = team.get("logo")
        if isinstance(logo, str) and logo.startswith("data:image/png;base64,"):
            body = base64.b64decode(logo.partition(",")[2], validate=True)
            digest = hashlib.sha256(body).hexdigest()
            _logos[digest] = body
            _logos.move_to_end(digest)
            while len(_logos) > 128:
                _logos.popitem(last=False)
            team = {**team, "logo": f"/espn/public/logos/{digest}"}
        teams.append(team)
    return {**payload, "teams": teams}


def _matches_etag(request, etag):
    return any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag.removeprefix("W/")
               for tag in request.headers.get("if-none-match", "").split(","))


@router.get("/public/logos/{digest}")
def public_logo(digest: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HTTPException(status_code=404, detail="logo not found")
    if digest not in _logos:
        payload = _public_payload(request)
        if payload:
            _external_logos(payload)
    body = _logos.get(digest)
    if body is None:
        raise HTTPException(status_code=404, detail="logo not found")
    headers = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": f'"{digest}"',
               "X-Content-Type-Options": "nosniff"}
    if _matches_etag(request, headers["ETag"]):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="image/png", headers=headers)


@router.get("/public/predictions/latest")
def latest(request: Request):
    payload = _public_payload(request)
    if payload is None:
        raise HTTPException(status_code=404, detail="no public predictions available")
    body = json.dumps(_external_logos(payload), separators=(",", ":"), ensure_ascii=False).encode()
    etag = f'W/"{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": "public, max-age=300", "ETag": etag, "Vary": "Accept-Encoding"}
    if _matches_etag(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
