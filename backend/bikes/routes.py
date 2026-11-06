"""Public Cozy Bikes API: live stations, waits at the nearest ones, and trip plans.

No auth: every answer comes from public Citi Bike data (live GBFS plus a model of
a year of trips). Built for people and agents alike; /bikes/agents.txt is the
plain-text guide, and /openapi.json has the schemas.
"""
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import re
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response

from . import conditions, gbfs, places, render
from .forecast import HORIZON_MIN, chance
from .model import SERVICE_AREA
from .plan import plan
from .wait import decide, distance_m, expected_wait_min, load_model, minutes_or_none, nearby

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
AGENTS_TXT = (Path(__file__).with_name('agents.txt')).read_text()
# Public origins for links in answers: the interactive page, and this API's map image.
SITE_URL = os.environ.get('COMMONS_SITE_URL', 'https://cozycommons.dev').rstrip('/')
API_URL = os.environ.get('PUBLIC_API_URL', 'https://api.cozycommons.dev').rstrip('/')
TILE_NAME = re.compile(r'^(index|\d{1,3}_\d{1,3})\.json$')


def live_model(when):
    """The model with this hour's weather factors, and what answers say about conditions."""
    model, summary = conditions.with_conditions(load_model(), when)
    note = conditions.describe(summary)
    return model, {**summary, 'note': note or None, 'alerts': gbfs.alerts(datetime.now(NEW_YORK))}


def with_note(message, about):
    extra = [about['note']] if about['note'] else []
    extra += [a['summary'] for a in about['alerts'] if a.get('summary')]
    return ' '.join([message, *extra])


def map_links(lat, lng, radius_m, need, marks=(), you=False):
    """`map_url` opens the interactive page on this view; `map_image` is the same view as a PNG."""
    view = f'lat={lat:.5f}&lng={lng:.5f}&need={need}&radius={round(radius_m)}'
    mark = f"&station={','.join(marks)}" if marks else ''
    return {'map_url': f'{SITE_URL}/bikes?{view}{mark}',
            'map_image': f"{API_URL}/bikes/map.png?{view}{mark}{'&you=1' if you else ''}"}


# Citi Bike names stations by cross streets ("W 31 St & 7 Ave"); fold how people
# write them ("west 31st street", "7th avenue") onto those words.
WORDS = {'street': 'st', 'avenue': 'ave', 'av': 'ave', 'east': 'e', 'west': 'w', 'north': 'n', 'south': 's',
         'place': 'pl', 'boulevard': 'blvd', 'road': 'rd', 'square': 'sq', 'and': '&'}


def search_words(text):
    words = re.findall(r'[a-z0-9&]+', text.lower())
    return [WORDS.get(w, re.sub(r'^(\d+)(st|nd|rd|th)$', r'\1', w)) for w in words]


def matches(name, words):
    tokens = search_words(name)
    # Numbers match whole words, so "31" does not find "231 St".
    return all(w in tokens if w.isdigit() else any(t.startswith(w) for t in tokens) for w in words)


def freshness():
    """Citi Bike's own time for the live data, and how long ago this server fetched it."""
    updated = gbfs.feed_updated_at()
    return {'feed_updated_at': None if updated is None
            else datetime.fromtimestamp(updated, NEW_YORK).isoformat(timespec='seconds'),
            'age_s': round(gbfs.status_age_s())}


def live_counts(dock, now):
    age = dock.report_age_s(now)
    return {'station': dock.name, 'station_id': dock.short_name, 'lat': dock.lat, 'lng': dock.lng,
            'bikes': dock.bikes, 'ebikes': dock.ebikes, 'classic_bikes': dock.bikes - dock.ebikes,
            'open_docks': dock.docks, 'docks_disabled': dock.docks_disabled,
            'renting': dock.renting, 'returning': dock.returning,
            'reported_s': None if age is None else round(age), 'stale': dock.stale(now)}


def find_station(docks, station_id):
    dock = next((d for d in docks if d.short_name == station_id), None)
    if dock is None:
        raise HTTPException(404, 'No such station in service. Search with /bikes/stations?q=.')
    return dock


def point(docks, lat, lng, station, name):
    """(lat, lng) from coordinates or a station id; exactly one of them."""
    if station is not None:
        if lat is not None or lng is not None:
            raise HTTPException(422, f'Give {name} coordinates or a station, not both.')
        dock = find_station(docks, station)
        return dock.lat, dock.lng
    if lat is None or lng is None:
        raise HTTPException(422, f'Give {name} as lat and lng, or as a station id.')
    return lat, lng


@router.get('/agents.txt', response_class=PlainTextResponse)
def agents_txt():
    """How to use this API, for agents and people."""
    return AGENTS_TXT


@router.get('/stations')
def stations(
    q: str = Query('', max_length=80, description='Cross streets, e.g. "broadway e 14" or "west 31st 7th avenue"'),
    lat: float | None = Query(None, **LAT), lng: float | None = Query(None, **LNG),
    limit: int = Query(10, ge=1, le=50),
):
    """Search live stations by name; with lat and lng, nearest first."""
    docks = live_docks()
    words = search_words(q)
    found = [d for d in docks if matches(d.name, words)]
    if lat is not None and lng is not None:
        found.sort(key=lambda d: distance_m(lat, lng, d.lat, d.lng))
    else:
        found.sort(key=lambda d: d.name)
    now = datetime.now(NEW_YORK)
    return {**freshness(), 'stations': [live_counts(d, now) for d in found[:limit]]}


@router.get('/places')
def find_places(q: str = Query(..., min_length=2, max_length=80,
                               description='An address, street or place: "123 w 14th st", "barclays center"'),
                lat: float | None = Query(None, **LAT), lng: float | None = Query(None, **LNG),
                limit: int = Query(8, ge=1, le=20)):
    """Addresses and named places near Citi Bike, from OpenStreetMap (no outside service);
    with lat and lng, equally good matches nearest first. Answer from one with /bikes/wait?lat=&lng=."""
    near = (lat, lng) if lat is not None and lng is not None else None
    return {'places': places.search(q, limit, near), 'attribution': '© OpenStreetMap contributors'}


@router.get('/stations/{station_id}')
def station(station_id: str):
    """One station's live counts, and the chance each is still there in 15, 30 and 60 minutes."""
    dock = find_station(live_docks(), station_id)
    now = datetime.now(NEW_YORK)
    model, about = live_model(now)
    odds = {need: {f'{m}_min': None if dock.stale(now) or (p := chance(model, dock, need, now, m)) is None
                   else round(p, 3) for m in (15, 30, 60)} for need in ('bike', 'ebike', 'dock')}
    return {**live_counts(dock, now), **freshness(), 'chance': odds, 'conditions': about,
            **map_links(dock.lat, dock.lng, 500, 'bike', [dock.short_name]),
            'wait_if_empty_min': minutes_or_none(expected_wait_min(model, dock.short_name, now, 'arrivals')),
            'wait_if_full_min': minutes_or_none(expected_wait_min(model, dock.short_name, now, 'stations'))}


def new_york(at):
    """A time without an offset is New York time, within a year of now (422 otherwise)."""
    try:
        when = at.replace(tzinfo=NEW_YORK) if at.tzinfo is None else at.astimezone(NEW_YORK)
        if abs(when - datetime.now(NEW_YORK)) <= timedelta(days=366):
            return when
    except OverflowError:
        pass
    raise HTTPException(422, 'Pick a time within a year of now.')


@router.get('/live')
def live():
    """Every station in service now, columnar, for the live map."""
    docks, now = live_docks(), datetime.now(NEW_YORK)
    return {
        **freshness(),
        'stations': {
            'id': [d.short_name for d in docks], 'name': [d.name for d in docks],
            'lat': [round(d.lat, 5) for d in docks], 'lng': [round(d.lng, 5) for d in docks],
            'bikes': [d.bikes for d in docks], 'ebikes': [d.ebikes for d in docks], 'docks': [d.docks for d in docks],
            'docks_disabled': [d.docks_disabled for d in docks],
            'reported_s': [None if (age := d.report_age_s(now)) is None else round(age) for d in docks],
            # 1 renting, 2 returning, 4 no report for 15 minutes (counts may be wrong)
            'flags': [int(d.renting) | int(d.returning) << 1 | int(d.stale(now)) << 2 for d in docks],
        },
    }


@router.get('/plan')
def plan_trip(
    from_lat: float | None = Query(None, **LAT), from_lng: float | None = Query(None, **LNG),
    to_lat: float | None = Query(None, **LAT), to_lng: float | None = Query(None, **LNG),
    from_station: str | None = Query(None, description='A station id instead of from_lat and from_lng'),
    to_station: str | None = Query(None, description='A station id instead of to_lat and to_lng'),
    # Omit to leave now. Chances use live counts for departures up to an hour ahead.
    depart: datetime | None = None,
    ebike: bool = False,
    format: Literal['json', 'text'] = 'json',
):
    """Best start and end stations for a trip, with the chance each has a bike or dock."""
    docks = live_docks()
    origin = point(docks, from_lat, from_lng, from_station, 'from')
    destination = point(docks, to_lat, to_lng, to_station, 'to')
    now = datetime.now(NEW_YORK)
    leave = now if depart is None else max(new_york(depart), now - timedelta(minutes=5))
    live = (leave - now).total_seconds() / 60 <= HORIZON_MIN
    model, about = live_model(leave)
    result = plan(model, docks, origin, destination, now, leave, live, ebike)
    # `answer` is the recommendation alone (the page shows conditions apart); `message` adds them for speech.
    result['answer'] = result['message']
    result['message'] = with_note(result['message'], about)
    if format == 'text':
        return PlainTextResponse(result['message'])
    links = {}
    if result['best']:
        start, end = result['best']['start'], result['best']['end']
        mid_lat, mid_lng = (start['lat'] + end['lat']) / 2, (start['lng'] + end['lng']) / 2
        span = distance_m(start['lat'], start['lng'], end['lat'], end['lng'])
        links = map_links(mid_lat, mid_lng, min(3000, max(600, span * 0.65)), 'ebike' if ebike else 'bike',
                          [start['station_id'], end['station_id']])
    return {**result, **freshness(), **links, 'conditions': about}


@router.get('/wait')
def wait(
    lat: float | None = Query(None, **LAT),
    lng: float | None = Query(None, **LNG),
    station: str | None = Query(None, description='A station id instead of lat and lng: start from that station'),
    need: Literal['bike', 'ebike', 'dock'] = 'bike',
    # Omit for now with live dock counts; any other time answers from history only.
    at: datetime | None = None,
    limit: int = Query(3, ge=1, le=10),
    include: str | None = Query(None, description='A station id to also answer, as `selected`, from the same place'),
    format: Literal['json', 'text'] = 'json',
):
    """The nearest stations, and how long until you have a bike (or dock) at each."""
    docks = live_docks()
    lat, lng = point(docks, lat, lng, station, 'the place')
    when = datetime.now(NEW_YORK) if at is None else new_york(at)
    model, about = live_model(when)
    extra = None if include is None else find_station(docks, include)
    result = nearby(model, docks, lat, lng, when, need, live=at is None, limit=limit, include=extra)
    # `answer` is the recommendation alone (the page shows conditions apart); `message` adds them for speech.
    result['answer'] = result['message']
    result['message'] = with_note(result['message'], about)
    if format == 'text':
        return PlainTextResponse(result['message'])
    best = result['best']
    links = map_links(lat, lng, 600, need, [best['station_id']] if best else [], you=station is None)
    return {**result, **freshness(), **links, 'conditions': about, 'model_window': model['window']}


@router.get('/wait-or-ride')
def wait_or_ride(
    # The service area, so a stray location cannot pick a dock 100 km away.
    lat: float = Query(**LAT),
    lng: float = Query(**LNG),
    format: Literal['json', 'text'] = 'json',
):
    docks = live_docks()
    now = datetime.now(NEW_YORK)
    model, about = live_model(now)
    result = decide(model, docks, lat, lng, now)
    # `answer` is the recommendation alone (the page shows conditions apart); `message` adds them for speech.
    result['answer'] = result['message']
    result['message'] = with_note(result['message'], about)
    if format == 'text':
        # Siri Shortcuts read this aloud.
        return PlainTextResponse(result['message'])
    return {**result, 'model_window': model['window']}


@router.get('/map/{name}')
def map_tile(name: str):
    """A street basemap tile (see bikes.basemap); the page draws them, and so does /map.png."""
    if not TILE_NAME.match(name) or not (render.MAP_DIR / name).is_file():
        raise HTTPException(404, 'No such map tile.')
    return FileResponse(render.MAP_DIR / name, media_type='application/json',
                        headers={'Cache-Control': 'public, max-age=86400'})


@router.get('/map.png', response_class=Response)
def map_png(
    lat: float | None = Query(None, **LAT), lng: float | None = Query(None, **LNG),
    radius: int = Query(600, ge=200, le=3000, description='Meters from the center to each edge'),
    need: Literal['bike', 'ebike', 'dock'] = 'bike',
    station: str | None = Query(None, max_length=40, description='Up to two station ids to mark, comma-separated'),
    you: bool = Query(False, description='Draw a "you are here" dot at the center'),
):
    """Live stations over the street map, as a PNG an agent can show. Centers on lat/lng, else the first station."""
    docks, now = live_docks(), datetime.now(NEW_YORK)
    marks = [s for s in (station or '').split(',') if s][:2]
    if lat is None or lng is None:
        if not marks:
            raise HTTPException(422, 'Give lat and lng, or a station.')
        first = find_station(docks, marks[0])
        lat, lng = first.lat, first.lng
    # Renders are shared for a minute per view, so the public route cannot be made to redraw on demand.
    key = (round(lat, 4), round(lng, 4), radius, need, tuple(marks), you, gbfs.feed_updated_at())
    stamp = f"Citi Bike {now:%-I:%M %p}"
    png = render.cached_render(key, lambda: render.render(docks, now, lat, lng, radius, need, marks, you, stamp))
    return Response(png, media_type='image/png', headers={'Cache-Control': 'public, max-age=60'})
