"""Public Cozy Bikes API: should you wait at a full dock or ride to another?"""
from datetime import datetime
import logging
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from . import gbfs
from .model import SERVICE_AREA
from .wait import decide, load_model, nearby

router = APIRouter()
logger = logging.getLogger(__name__)
NEW_YORK = ZoneInfo('America/New_York')


def live_docks():
    try:
        return gbfs.docks()
    except gbfs.GbfsError as error:
        logger.warning('Citi Bike GBFS unavailable: %s', error)
        raise HTTPException(503, 'Live Citi Bike dock data is unavailable. Try again in a minute.') from None


@router.get('/wait')
def wait(
    lat: float = Query(ge=SERVICE_AREA[0], le=SERVICE_AREA[1]),
    lng: float = Query(ge=SERVICE_AREA[2], le=SERVICE_AREA[3]),
    need: Literal['bike', 'dock'] = 'bike',
    # Omit for now with live dock counts; any other time answers from history only.
    # A time without an offset is New York time.
    at: datetime | None = None,
    limit: int = Query(3, ge=1, le=10),
    format: Literal['json', 'text'] = 'json',
):
    """The nearest stations, and how long until you have a bike (or dock) at each."""
    when = datetime.now(NEW_YORK) if at is None else (
        at.replace(tzinfo=NEW_YORK) if at.tzinfo is None else at.astimezone(NEW_YORK))
    result = nearby(load_model(), live_docks(), lat, lng, when, need, live=at is None, limit=limit)
    if format == 'text':
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': load_model()['window']}


@router.get('/wait-or-ride')
def wait_or_ride(
    # The service area, so a stray location cannot pick a dock 100 km away.
    lat: float = Query(ge=SERVICE_AREA[0], le=SERVICE_AREA[1]),
    lng: float = Query(ge=SERVICE_AREA[2], le=SERVICE_AREA[3]),
    format: Literal['json', 'text'] = 'json',
):
    docks = live_docks()
    model = load_model()
    result = decide(model, docks, lat, lng, datetime.now(NEW_YORK))
    if format == 'text':
        # Siri Shortcuts read this aloud.
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': model['window']}
