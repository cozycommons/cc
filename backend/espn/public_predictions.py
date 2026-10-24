"""Allowlisted public league estimates, uploaded without contacting ESPN."""

import hmac
import os
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator,
    model_validator,
)

MAX_BODY_BYTES = 256 * 1024
Number = Annotated[float, Field(allow_inf_nan=False)]
Chance = Annotated[Number, Field(ge=0, le=100)]
MatchupId = Annotated[int, Field(ge=-(2**63), le=2**63 - 1)]
Games = Annotated[int, Field(ge=0, le=20)]
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


class PublicPrediction(PublicModel):
    home: PublicTeam
    away: PublicTeam
    scores: tuple[Number, Number]
    projected_totals: tuple[Number, Number]
    chance: Chance
    range: tuple[Number, Number]
    margin_80: tuple[Number, Number]
    days: list[PublicDay] = Field(max_length=14)
    odds_history: list[PublicOddsPoint] = Field(max_length=30)

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


async def _read_snapshot(request: Request, _auth=Depends(_upload_auth)) -> PublicSnapshot:
    # Bound the actual stream before parsing, including chunked/undeclared bodies.
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="snapshot exceeds 256 KiB")
        raw.extend(chunk)
    try:
        return PublicSnapshot.model_validate_json(raw)
    except ValidationError:
        # Do not echo rejected private fields or non-finite JSON values in errors.
        raise HTTPException(status_code=422, detail="invalid public-v1 snapshot")


@router.post("/public/predictions")
def upload(request: Request, snapshot: PublicSnapshot = Depends(_read_snapshot)):
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


@router.get("/public/predictions/latest")
def latest(request: Request, response: Response):
    # One fixed query: public callers cannot vary the shared cache key.
    result = request.app.state.supabase.table("espn_public_predictions").select(
        "payload"
    ).order("received_at", desc=True).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="no public predictions available")
    response.headers["Cache-Control"] = "public, max-age=300"
    return result.data[0]["payload"]
