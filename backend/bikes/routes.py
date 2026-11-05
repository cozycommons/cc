"""Public Cozy Bikes API: should you wait at a full dock or ride to another?"""
from datetime import datetime
import logging
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from . import gbfs
from .wait import decide, load_model

router = APIRouter()
logger = logging.getLogger(__name__)
NEW_YORK = ZoneInfo('America/New_York')


@router.get('/wait-or-ride')
def wait_or_ride(
    # Roughly the Citi Bike service area, so a stray location cannot pick a dock 100 km away.
    lat: float = Query(ge=40.45, le=40.95),
    lng: float = Query(ge=-74.30, le=-73.70),
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
