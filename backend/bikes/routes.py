"""Public Cozy Bikes API: live stations, waits at the nearest ones, and trip plans."""
from datetime import datetime, timedelta
import logging
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from . import gbfs
from .forecast import HORIZON_MIN
from .model import SERVICE_AREA
from .plan import plan
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


LAT = dict(ge=SERVICE_AREA[0], le=SERVICE_AREA[1])
LNG = dict(ge=SERVICE_AREA[2], le=SERVICE_AREA[3])


def new_york(at):
    """A time without an offset is New York time."""
    return at.replace(tzinfo=NEW_YORK) if at.tzinfo is None else at.astimezone(NEW_YORK)


@router.get('/live')
def live():
    """Every station in service now, columnar, for the live map."""
    docks = live_docks()
    return {
        'age_s': round(gbfs.status_age_s()),
        'stations': {
            'id': [d.short_name for d in docks], 'name': [d.name for d in docks],
            'lat': [round(d.lat, 5) for d in docks], 'lng': [round(d.lng, 5) for d in docks],
            'bikes': [d.bikes for d in docks], 'ebikes': [d.ebikes for d in docks], 'docks': [d.docks for d in docks],
            # 1 renting, 2 returning
            'flags': [int(d.renting) | int(d.returning) << 1 for d in docks],
        },
    }


@router.get('/plan')
def plan_trip(
    from_lat: float = Query(**LAT), from_lng: float = Query(**LNG),
    to_lat: float = Query(**LAT), to_lng: float = Query(**LNG),
    # Omit to leave now. Chances use live counts for departures up to an hour ahead.
    depart: datetime | None = None,
    ebike: bool = False,
    format: Literal['json', 'text'] = 'json',
):
    """Best start and end stations for a trip, with the chance each has a bike or dock."""
    now = datetime.now(NEW_YORK)
    leave = now if depart is None else max(new_york(depart), now - timedelta(minutes=5))
    live = (leave - now).total_seconds() / 60 <= HORIZON_MIN
    result = plan(load_model(), live_docks(), (from_lat, from_lng), (to_lat, to_lng), now, leave, live, ebike)
    if format == 'text':
        return PlainTextResponse(result['message'])
    return result


@router.get('/wait')
def wait(
    lat: float = Query(**LAT),
    lng: float = Query(**LNG),
    need: Literal['bike', 'ebike', 'dock'] = 'bike',
    # Omit for now with live dock counts; any other time answers from history only.
    at: datetime | None = None,
    limit: int = Query(3, ge=1, le=10),
    format: Literal['json', 'text'] = 'json',
):
    """The nearest stations, and how long until you have a bike (or dock) at each."""
    when = datetime.now(NEW_YORK) if at is None else new_york(at)
    result = nearby(load_model(), live_docks(), lat, lng, when, need, live=at is None, limit=limit)
    if format == 'text':
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': load_model()['window']}


@router.get('/wait-or-ride')
def wait_or_ride(
    # The service area, so a stray location cannot pick a dock 100 km away.
    lat: float = Query(**LAT),
    lng: float = Query(**LNG),
    format: Literal['json', 'text'] = 'json',
):
    docks = live_docks()
    model = load_model()
    result = decide(model, docks, lat, lng, datetime.now(NEW_YORK))
    if format == 'text':
        # Siri Shortcuts read this aloud.
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': model['window']}
