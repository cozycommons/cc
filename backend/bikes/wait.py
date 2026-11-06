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

from .conditions import holiday
from .forecast import chance, rate
from .model import MODEL_PATH

# Crow-flies walking speed: about 1.3 m/s on the street grid with a 1.3x detour.
WALK_MPS = 1.0
SEARCH_M = 1500
# Beyond this, say which dock the answer is about.
NEAR_M = 150
# Station reports are normally 1-4 minutes old; past this, do not trust the counts.
STALE_S = 900


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
    ebikes: int = 0
    # Epoch seconds of the station's own last report; 0 when the feed gives none.
    reported: int = 0
    docks_disabled: int = 0

    def report_age_s(self, now):
        return max(0, now.timestamp() - self.reported) if self.reported else None

    def stale(self, now):
        """Silent long enough that its counts may be wrong (some stations stop reporting for hours)."""
        age = self.report_age_s(now)
        return age is not None and age > STALE_S


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
    per_hour = rate(model, rates, short_name, when)
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


def since(seconds):
    """How long a station has been silent; some report timestamps near 1970."""
    if seconds < 90 * 60:
        return minutes(seconds / 60)
    if seconds < 48 * 3600:
        return f'{round(seconds / 3600)} hours'
    return 'over a day'


def minutes_or_none(value):
    return None if value is None else round(value, 1)


def describe_when(when):
    day = holiday(when.date())
    kind = day if day else f"a {'weekend' if when.weekday() >= 5 else 'weekday'}"
    return f"{when.hour % 12 or 12} {'AM' if when.hour < 12 else 'PM'} on {kind}"


NEEDS = {
    # need: (live count attribute, refill rates, what refills it, noun)
    'bike': ('bikes', 'arrivals', 'a bike usually comes back', 'bike'),
    'ebike': ('ebikes', 'arrivals', 'an e-bike usually comes back', 'e-bike'),
    'dock': ('docks', 'stations', 'a dock usually opens', 'open dock'),
}


def station_entry(model, dock, lat, lng, when):
    away_m = distance_m(lat, lng, dock.lat, dock.lng)
    walk = away_m / WALK_MPS / 60
    arrive = when + timedelta(minutes=walk)
    return {
        'station': dock.name, 'station_id': dock.short_name, 'lat': dock.lat, 'lng': dock.lng,
        'distance_m': round(away_m), 'walk_min': round(walk, 1),
        'wait_if_empty_min': minutes_or_none(expected_wait_min(model, dock.short_name, arrive, 'arrivals')),
        'wait_if_full_min': minutes_or_none(expected_wait_min(model, dock.short_name, arrive, 'stations')),
    }, walk, arrive


def refill_wait(model, dock, need, when):
    wait = expected_wait_min(model, dock.short_name, when, NEEDS[need][1])
    if wait is not None and need == 'ebike':
        share = model.get('ebike_share', 0.0)
        wait = wait / share if share else None
    return wait


# A station that never refills at this hour costs an hour in the case it is gone.
NO_REFILL_MIN = 60.0


def refill_cost(wait):
    return NO_REFILL_MIN if wait is None else wait


# Below this, a message says how likely the bike or dock is to still be there.
MENTION_BELOW = 0.95


def live_fields(model, dock, need, now, walk, arrive):
    """Live counts, the chance it has what you need on arrival, and the expected minutes to have it."""
    attribute = NEEDS[need][0]
    count = getattr(dock, attribute)
    serving = dock.returning if need == 'dock' else dock.renting
    age = dock.report_age_s(now)
    live = {'bikes': dock.bikes, 'ebikes': dock.ebikes, 'open_docks': dock.docks, 'docks_disabled': dock.docks_disabled,
            'reported_s': None if age is None else round(age)}
    if dock.stale(now):
        return {**live, 'status': 'unknown', 'chance': None, 'wait_min': None, 'expected_min': None}
    status = 'closed' if not serving else 'available' if count > 0 else ('full' if need == 'dock' else 'empty')
    p = chance(model, dock, need, now, walk)
    wait = refill_wait(model, dock, need, arrive) if serving else None
    # Walk, plus the refill wait in the case it is gone (or still gone) when you arrive.
    expected = None if p is None else walk + (1 - p) * refill_cost(wait)
    return {
        **live, 'status': status,
        'chance': None if p is None else round(p, 3),
        'wait_min': minutes_or_none(wait),
        'expected_min': minutes_or_none(expected),
    }


def nearby(model, docks, lat, lng, when: datetime, need='bike', live=True, limit=3):
    """The `limit` nearest stations, each with its walk and expected waits, and the best one.

    Waits are read at arrival time (now plus the walk). With live data, each
    station also gets the chance it has what you need when you arrive (from its
    live count; see forecast.py) and the expected minutes until you have it: the
    walk, plus the refill wait weighted by the chance it is gone. `best` has the
    lowest expected minutes. Without live data (an arbitrary time), both
    conditional waits are given and there is no recommendation.
    """
    stations = []
    for dock in sorted(docks, key=lambda d: distance_m(lat, lng, d.lat, d.lng))[:limit]:
        entry, walk, arrive = station_entry(model, dock, lat, lng, when)
        if live:
            entry.update(live_fields(model, dock, need, when, walk, arrive))
        stations.append(entry)
    best = min((s for s in stations if live and s['expected_min'] is not None),
               key=lambda s: s['expected_min'], default=None)
    return {'need': need, 'at': when.isoformat(timespec='minutes'), 'live': live,
            'best': best, 'stations': stations, 'message': nearby_message(stations, best, need, live, when)}


def percent(p):
    return f'{min(99, round(p * 100))}%' if p < 0.995 else 'over 99%'


def nearby_message(stations, best, need, live, when):
    if not stations:
        return 'No Citi Bike stations found.'
    attribute, _, refill, noun = NEEDS[need]
    nearest = stations[0]
    if not live:
        empty, full = nearest['wait_if_empty_min'], nearest['wait_if_full_min']
        bike = 'bikes rarely come back then' if empty is None else f'a bike usually comes back in {duration(empty)}'
        dock = 'docks rarely open then' if full is None else f'a dock usually opens in {duration(full)}'
        return (f"At {describe_when(when)}, the nearest station is {nearest['station']}, "
                f"{minutes(nearest['walk_min'], True)} walk. If it is empty, {bike}; if it is full, {dock}.")
    if best is None:
        return f'No station nearby has {"an" if noun[0] in "aeo" else "a"} {noun}, and none usually gets one at this hour.'
    key = {'bikes': 'bikes', 'ebikes': 'ebikes', 'docks': 'open_docks'}[attribute]
    count = best[key]
    walk = f"Walk to {best['station']}, {minutes(best['walk_min'], True)} walk"
    if count > 0:
        message = f"{walk}: {count} {noun}{'' if count == 1 else 's'} now."
        if best['chance'] < MENTION_BELOW:
            message = message[:-1] + f", {percent(best['chance'])} likely one is left when you arrive."

    else:
        message = f"{walk}. It is {best['status']}, but {refill} in {duration(best['wait_min'])}."
        if best['chance'] >= 0.05:
            message += f" {percent(best['chance']).capitalize()} chance one is back by the time you arrive."
    if best is not nearest:
        if nearest['status'] == 'closed':
            reason = 'is closed'
        elif nearest['status'] == 'unknown':
            reason = f"has not reported for {since(nearest['reported_s'])}"

        elif nearest[key] > 0:
            reason = f"has {nearest[key]}, {percent(nearest['chance'])} likely to last until you arrive"
        elif nearest['wait_min'] is None:
            reason = f"is {nearest['status']} and rarely refills at this hour"
        else:
            reason = f"is {nearest['status']}: {duration(nearest['expected_min'])} expected"
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
