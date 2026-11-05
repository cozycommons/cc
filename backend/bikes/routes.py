"""Public Cozy Bikes API: should you wait at a full dock or ride to another?"""
from datetime import datetime
import logging
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from . import gbfs
from .model import SERVICE_AREA
from .wait import decide, load_model

router = APIRouter()
logger = logging.getLogger(__name__)
NEW_YORK = ZoneInfo('America/New_York')


@router.get('/wait-or-ride')
def wait_or_ride(
    # The service area, so a stray location cannot pick a dock 100 km away.
    lat: float = Query(ge=SERVICE_AREA[0], le=SERVICE_AREA[1]),
    lng: float = Query(ge=SERVICE_AREA[2], le=SERVICE_AREA[3]),
    format: Literal['json', 'text'] = 'json',
):
    try:
        docks = gbfs.docks()
    except gbfs.GbfsError as error:
        logger.warning('Citi Bike GBFS unavailable: %s', error)
        raise HTTPException(503, 'Live Citi Bike dock data is unavailable. Try again in a minute.') from None
    model = load_model()
    result = decide(model, docks, lat, lng, datetime.now(NEW_YORK))
    if format == 'text':
        # Siri Shortcuts read this aloud.
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': model['window']}
