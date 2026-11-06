"""Plan a Citi Bike trip: which station to start from and which to end at.

Each start and end pair costs the walk to the start, the ride between them, and
the walk from the end, plus each end's refill wait weighted by the chance it is
empty (start) or full (end) when you get there (forecast.py). The pair with the
lowest expected door-to-door minutes wins. Departures more than an hour away have
no useful live counts, so their chances are null and only the timing is planned.
"""
from datetime import timedelta

from .forecast import HORIZON_MIN, chance
from .wait import MENTION_BELOW, WALK_MPS, distance_m, duration, minutes, percent, refill_cost, refill_wait

CANDIDATES = 4
REACH_M = 1000


def candidates(docks, lat, lng, serving):
    near = sorted(((distance_m(lat, lng, d.lat, d.lng), d) for d in docks if serving(d)), key=lambda pair: pair[0])
    return [(gap, d) for gap, d in near[:CANDIDATES] if gap <= REACH_M] or near[:1]


def leg(model, dock, need, now, arrive, ahead):
    p = chance(model, dock, need, now, ahead) if ahead <= HORIZON_MIN else None
    wait = refill_wait(model, dock, need, arrive)
    risk = 0.0 if p is None else (1 - p) * refill_cost(wait)
    return p, wait, risk


def plan(model, docks, origin, destination, now, depart, live, ebike=False):
    """Best start and end stations from origin to destination, leaving at `depart`."""
    need = 'ebike' if ebike else 'bike'
    lead = (depart - now).total_seconds() / 60
    options = []
    # Stations that stopped reporting are left out: their counts may be hours old.
    for start_gap, start in candidates(docks, *origin, lambda d: d.renting and not d.stale(now)):
        walk_to = start_gap / WALK_MPS / 60
        at_start = depart + timedelta(minutes=walk_to)
        p_bike, bike_wait, bike_risk = leg(model, start, need, now, at_start, lead + walk_to) if live else (None, None, 0.0)
        for end_gap, end in candidates(docks, *destination, lambda d: d.returning and not d.stale(now)):
            if end is start:
                continue
            ride = distance_m(start.lat, start.lng, end.lat, end.lng) / model['ride_mps'] / 60
            walk_from = end_gap / WALK_MPS / 60
            at_end = at_start + timedelta(minutes=ride)
            p_dock, dock_wait, dock_risk = (leg(model, end, 'dock', now, at_end, lead + walk_to + ride)
                                            if live else (None, None, 0.0))
            options.append({
                'start': station_summary(start, walk_to, p_bike, bike_wait, need),
                'end': station_summary(end, walk_from, p_dock, dock_wait, 'dock'),
                'ride_min': round(ride, 1),
                'minutes': round(walk_to + ride + walk_from, 1),
                'expected_min': round(walk_to + ride + walk_from + bike_risk + dock_risk, 1),
            })
    options.sort(key=lambda o: o['expected_min'])
    walk_only = distance_m(*origin, *destination) / WALK_MPS / 60
    best = options[0] if options else None
    return {
        'depart': depart.isoformat(timespec='minutes'), 'live': live, 'need': need,
        'walk_only_min': round(walk_only, 1), 'best': best, 'alternatives': options[1:3],
        'message': plan_message(best, walk_only),
    }


def station_summary(dock, walk, p, wait, need):
    return {
        'station': dock.name, 'station_id': dock.short_name, 'lat': dock.lat, 'lng': dock.lng,
        'walk_min': round(walk, 1), 'bikes': dock.bikes, 'ebikes': dock.ebikes, 'open_docks': dock.docks,
        'chance': None if p is None else round(p, 3),
        'wait_if_missing_min': None if wait is None else round(wait, 1),
        'need': need,
    }


def plan_message(best, walk_only):
    if best is None:
        return 'No Citi Bike stations near both ends of this trip.'
    start, end = best['start'], best['end']

    def odds(leg, noun):
        if leg['chance'] is None or leg['chance'] >= MENTION_BELOW:
            return ''
        return f" ({percent(leg['chance'])} likely to have {noun})"
    bike = 'an e-bike' if start['need'] == 'ebike' else 'a bike'
    message = (f"Walk {minutes(start['walk_min'])} to {start['station']}{odds(start, bike)}, "
               f"ride {minutes(best['ride_min'])} to {end['station']}{odds(end, 'a dock')}, "
               f"then walk {minutes(end['walk_min'])}. About {minutes(best['expected_min'])}")
    if walk_only <= best['expected_min']:
        return message + f'. Walking the whole way is {duration(walk_only)}, so walk.'
    return message + f'; walking is {duration(walk_only)}.'
