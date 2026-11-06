"""Waiting at Citi Bike docks. Pure logic over the model and live docks.

A full dock frees a slot at its next departure, and an empty dock gets a bike at
its next arrival, so the expected wait is 60 / (trips per hour) for the station,
day type, hour and season.

`nearby` answers: which stations are closest, and how long until I have a bike
(or a dock) at each, walking there and waiting if it is empty (or full)?
`decide` answers the narrower full-dock case with a bike in hand: wait, or ride
on and walk back.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
import json
import math

from .model import MODEL_PATH

# Crow-flies walking speed: about 1.3 m/s on the street grid with a 1.3x detour.
WALK_MPS = 1.0
SEARCH_M = 1500
# Beyond this, say which dock the answer is about.
NEAR_M = 150


@dataclass(frozen=True)
class Dock:
    short_name: str
    name: str
    lat: float
    lng: float
    docks: int
    returning: bool
    bikes: int = 0
    renting: bool = True


@dataclass(frozen=True)
class Option:
    dock: Dock
    ride_min: float
    walk_min: float

    @property
    def total_min(self):
        return self.ride_min + self.walk_min


@cache
def load_model():
    return json.loads(MODEL_PATH.read_text())


def distance_m(a_lat, a_lng, b_lat, b_lng):
    dlat, dlng = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(dlng / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def expected_wait_min(model, short_name, when, rates='stations'):
    """Minutes until the next departure (rates='stations') or arrival (rates='arrivals'),
    or None for a dock with no such trips then."""
    slots = model[rates].get(short_name)
    if not slots:
        return None
    per_hour = slots[24 * (when.weekday() >= 5) + when.hour] / 100 * model['month_factor'][when.month - 1]
    return 60 / per_hour if per_hour > 0 else None


def minutes(value, adjective=False):
    count = max(1, round(value))
    if adjective:
        # "an 8-minute ride", "an 11-minute walk"
        return f"{'an' if str(count).startswith('8') or count in (11, 18) else 'a'} {count}-minute"
    return f"{count} minute{'s' if count != 1 else ''}"


def duration(value):
    """Spoken wait: minutes under 90, then hours."""
    if value < 90:
        return f'about {minutes(value)}'
    hours = round(value / 60)
    return f"about {hours} hour{'s' if hours != 1 else ''}"


def minutes_or_none(value):
    return None if value is None else round(value, 1)


def describe_when(when):
    return f"{when.hour % 12 or 12} {'AM' if when.hour < 12 else 'PM'} on a {'weekend' if when.weekday() >= 5 else 'weekday'}"


def nearby(model, docks, lat, lng, when: datetime, need='bike', live=True, limit=3):
    """The `limit` nearest stations, each with its walk and expected waits, and the best one.

    Waits are read at arrival time (now plus the walk). With live data, a station
    that has what you need costs only the walk; an empty (or full) one adds the
    expected wait for an arrival (or departure); one not renting (or returning)
    is out. Without live data (an arbitrary time), both conditional waits are
    given and there is no recommendation.
    """
    rates, have = ('arrivals', 'bikes') if need == 'bike' else ('stations', 'docks')
    stations = []
    for dock in sorted(docks, key=lambda d: distance_m(lat, lng, d.lat, d.lng))[:limit]:
        away_m = distance_m(lat, lng, dock.lat, dock.lng)
        walk = away_m / WALK_MPS / 60
        arrive = when + timedelta(minutes=walk)
        entry = {
            'station': dock.name, 'station_id': dock.short_name, 'lat': dock.lat, 'lng': dock.lng,
            'distance_m': round(away_m), 'walk_min': round(walk, 1),
            'wait_if_empty_min': minutes_or_none(expected_wait_min(model, dock.short_name, arrive, 'arrivals')),
            'wait_if_full_min': minutes_or_none(expected_wait_min(model, dock.short_name, arrive, 'stations')),
        }
        if live:
            count, serving = (dock.bikes, dock.renting) if need == 'bike' else (dock.docks, dock.returning)
            wait = 0.0 if serving and count > 0 else (
                expected_wait_min(model, dock.short_name, arrive, rates) if serving else None)
            entry.update({
                'bikes': dock.bikes, 'open_docks': dock.docks,
                'status': 'closed' if not serving else 'available' if count > 0 else (
                    'empty' if need == 'bike' else 'full'),
                'wait_min': minutes_or_none(wait),
                'total_min': None if wait is None else round(walk + wait, 1),
            })
        stations.append(entry)
    best = min((s for s in stations if live and s['total_min'] is not None),
               key=lambda s: s['total_min'], default=None)
    return {'need': need, 'at': when.isoformat(timespec='minutes'), 'live': live,
            'best': best, 'stations': stations, 'message': nearby_message(stations, best, need, live, when)}


def nearby_message(stations, best, need, live, when):
    if not stations:
        return 'No Citi Bike stations found.'
    item = 'a bike' if need == 'bike' else 'a dock'
    nearest = stations[0]
    if not live:
        empty, full = nearest['wait_if_empty_min'], nearest['wait_if_full_min']
        bike = 'bikes rarely come back then' if empty is None else f'a bike usually comes back in {duration(empty)}'
        dock = 'docks rarely open then' if full is None else f'a dock usually opens in {duration(full)}'
        return (f"At {describe_when(when)}, the nearest station is {nearest['station']}, "
                f"{minutes(nearest['walk_min'], True)} walk. If it is empty, {bike}; if it is full, {dock}.")
    if best is None:
        return f'No station nearby has {item}, and none usually gets one at this hour.'
    walk = f"Walk to {best['station']}, {minutes(best['walk_min'], True)} walk"
    if best['wait_min'] == 0:
        count = best['bikes'] if need == 'bike' else best['open_docks']
        noun = ('bike' if need == 'bike' else 'open dock') + ('' if count == 1 else 's')
        message = f'{walk}: {count} {noun} now.'
    else:
        verb = 'a bike usually comes back' if need == 'bike' else 'a dock usually opens'
        message = f"{walk}. It is {best['status']}, but {verb} in {duration(best['wait_min'])}."
    # An available nearest station is always best, so here it is closed, empty or full.
    if best is not nearest:
        if nearest['status'] == 'closed':
            reason = 'is closed'
        elif nearest['total_min'] is None:
            reason = f"is {nearest['status']} and rarely gets {item} at this hour"
        else:
            reason = f"is {nearest['status']}: {duration(nearest['total_min'])} with the wait"
        message += f" The nearest, {nearest['station']}, {reason}."
    return message


def decide(model, docks, lat, lng, when: datetime):
    here = min(docks, key=lambda d: distance_m(lat, lng, d.lat, d.lng))
    away_m = distance_m(lat, lng, here.lat, here.lng)
    result = {'station': here.name, 'station_id': here.short_name, 'distance_m': round(away_m),
              'open_docks': here.docks, 'wait_min': None, 'alternative': None}
    prefix = f'The nearest dock is {here.name}, {round(away_m)} m away. ' if away_m > NEAR_M else ''
    if here.returning and here.docks > 0:
        noun = 'dock' if here.docks == 1 else 'docks'
        return {**result, 'decision': 'dock', 'message': f'{prefix}Dock now at {here.name}: {here.docks} open {noun}.'}

    wait = expected_wait_min(model, here.short_name, when)
    options = []
    for dock in docks:
        if dock is here or not dock.returning or dock.docks <= 0:
            continue
        gap = distance_m(here.lat, here.lng, dock.lat, dock.lng)
        if gap <= SEARCH_M:
            options.append(Option(dock, gap / model['ride_mps'] / 60, gap / WALK_MPS / 60))
    best = min(options, key=lambda o: o.total_min, default=None)
    result['wait_min'] = None if wait is None else round(wait, 1)
    if best:
        result['alternative'] = {'station': best.dock.name, 'station_id': best.dock.short_name,
                                 'open_docks': best.dock.docks, 'ride_min': round(best.ride_min, 1),
                                 'walk_min': round(best.walk_min, 1)}
    usual = 'Nobody usually takes a bike out here at this hour' if wait is None else \
        f'A dock here usually opens in about {minutes(wait)}'
    if best and (wait is None or best.total_min < wait):
        return {**result, 'decision': 'ride', 'message': (
            f'{prefix}Ride to {best.dock.name}: {best.dock.docks} open, {minutes(best.ride_min, True)} ride '
            f'and {minutes(best.walk_min, True)} walk back. {usual}.')}
    if wait is not None:
        other = (f' Riding to {best.dock.name} would take {minutes(best.total_min)} with the walk back.'
                 if best else '')
        return {**result, 'decision': 'wait', 'message': f'{prefix}Wait. {usual}.{other}'}
    return {**result, 'decision': 'unknown', 'message': (
        f'{prefix}{here.name} is full, there is no open dock within {SEARCH_M / 1000:g} km, '
        'and bikes rarely leave here at this hour.')}
