"""Wait at a full dock, or ride to an open one? Pure logic over the model and live docks.

A full dock frees a slot at its next departure, so the expected wait is
60 / (departures per hour) for the station, day type, hour and season. Riding on
costs the ride to the open dock plus the walk back, since the full dock stands in
for where you were going.
"""
from dataclasses import dataclass
from datetime import datetime
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


def expected_wait_min(model, short_name, when):
    """Minutes until the next departure, or None for a dock with no departures then."""
    slots = model['stations'].get(short_name)
    if not slots:
        return None
    per_hour = slots[24 * (when.weekday() >= 5) + when.hour] / 100 * model['month_factor'][when.month - 1]
    return 60 / per_hour if per_hour > 0 else None


def minutes(value, adjective=False):
    count = max(1, round(value))
    if adjective:
        return f'{count}-minute'
    return f"{count} minute{'s' if count != 1 else ''}"


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
            f'{prefix}Ride to {best.dock.name}: {best.dock.docks} open, a {minutes(best.ride_min, True)} ride '
            f'and a {minutes(best.walk_min, True)} walk back. {usual}.')}
    if wait is not None:
        other = (f' Riding to {best.dock.name} would take {minutes(best.total_min)} with the walk back.'
                 if best else '')
        return {**result, 'decision': 'wait', 'message': f'{prefix}Wait. {usual}.{other}'}
    return {**result, 'decision': 'unknown', 'message': (
        f'{prefix}{here.name} is full, there is no open dock within {SEARCH_M / 1000:g} km, '
        'and bikes rarely leave here at this hour.')}
