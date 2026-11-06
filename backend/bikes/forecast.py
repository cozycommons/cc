"""Chance a station still has a bike (or dock) when you get there.

A station's available bikes move like a bounded birth-death chain: riders return
bikes at the station's arrival rate and take them at its departure rate, for the
hour and season, and the count stays between 0 and the docks in service (bikes
plus open docks now). Starting from the live count, the chain steps forward in
STEP_S ticks to the arrival time. Rebalancing vans and riders already waiting are
not in the trip data, so they are not in the forecast.
"""
from datetime import timedelta

from .conditions import day_type, hour_factor

STEP_S = 10
# Past this, live counts say little about arrival and history alone answers.
HORIZON_MIN = 60


def rate(model, rates, short_name, when):
    """Trips per hour at a station: its average for the day type and hour, scaled for the
    season and, when the model carries live conditions, for that hour's weather."""
    slots = model[rates].get(short_name)
    if not slots:
        return 0.0
    return (slots[24 * day_type(when) + when.hour] / 100 * model['month_factor'][when.month - 1]
            * hour_factor(model, when))


def per_step(model, rates, short_name, when, share):
    return rate(model, rates, short_name, when) * share * STEP_S / 3600


def distribution(model, short_name, count, capacity, start, minutes, share=1.0):
    """Probabilities of 0..capacity available after `minutes`, from `count` now."""
    p = [0.0] * (capacity + 1)
    p[min(max(count, 0), capacity)] = 1.0
    hour = None
    for step in range(round(minutes * 60 / STEP_S)):
        when = start + timedelta(seconds=step * STEP_S)
        if when.hour != hour:
            hour = when.hour
            # At most one event per tick keeps the chain a valid distribution.
            up = min(per_step(model, 'arrivals', short_name, when, share), 0.5)
            down = min(per_step(model, 'stations', short_name, when, share), 0.5)
        q = [0.0] * (capacity + 1)
        for k, mass in enumerate(p):
            if not mass:
                continue
            gain = up if k < capacity else 0.0
            loss = down if k > 0 else 0.0
            q[k] += mass * (1 - gain - loss)
            if gain:
                q[k + 1] += mass * gain
            if loss:
                q[k - 1] += mass * loss
        p = q
    return p


def chance(model, dock, need, start, minutes):
    """P(what you need is there after `minutes`), or None past the horizon or out of service."""
    serving = dock.returning if need == 'dock' else dock.renting
    if not serving or minutes > HORIZON_MIN:
        return None
    capacity = dock.bikes + dock.docks
    if capacity <= 0:
        return 0.0
    if need == 'ebike':
        # E-bikes share the docks; their flows are the e-bike share of all trips.
        p = distribution(model, dock.short_name, dock.ebikes, capacity, start, minutes, model.get('ebike_share', 0.0))
        return 1 - p[0]
    p = distribution(model, dock.short_name, dock.bikes, capacity, start, minutes)
    return 1 - (p[-1] if need == 'dock' else p[0])
