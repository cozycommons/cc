"""What makes this hour unlike an average one: weather and holidays.

The model's rates are averages over a year. A year of hourly Citi Bike trips
against Central Park's observed weather (bikes.model) shows how far conditions
move them: heavy rain cuts trips to about 0.26x, rain to about 0.43x, snow below
freezing to about 0.17x, a dry hour below freezing to about 0.8x, and days after
a snowstorm stay low. `multiplier` applies
the fitted factor for an hour; holidays use the weekend profile.

Live weather comes from Open-Meteo's forecast (no key, CC BY 4.0), cached for 30
minutes. If it is unavailable, rates are unadjusted and answers say so.
"""
from datetime import date, datetime, timedelta
import json
import logging
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

# Central Park, the reference station for the city's weather.
FORECAST_URL = ('https://api.open-meteo.com/v1/forecast?latitude=40.7812&longitude=-73.9665'
                '&hourly=temperature_2m,precipitation,snowfall&past_days=3&forecast_days=3'
                '&timezone=America%2FNew_York')
TTL_S = 1800.0
MAX_STALE_S = 6 * 3600.0
FAIL_COOLDOWN_S = 300.0
TIMEOUT_S = 4
MAX_BYTES = 1_000_000
# Snow on the ground keeps riders away for days after the storm.
SNOW_AFTER_CM = 2.0


def sky(precip_mm, snow_cm):
    if snow_cm > 0.1:
        return 'snow'
    if precip_mm >= 2.5:
        return 'heavy rain'
    if precip_mm >= 0.5:
        return 'rain'
    return 'drizzle' if precip_mm > 0 else 'dry'


def heat(temp_c):
    if temp_c < 0:
        return 'below 0C'
    if temp_c < 10:
        return '0-10C'
    if temp_c < 25:
        return '10-25C'
    return '25-30C' if temp_c < 30 else '30C+'


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day):
    # A Saturday holiday is observed Friday, a Sunday one Monday.
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def holidays(year):
    fixed = {'New Year’s Day': date(year, 1, 1), 'Juneteenth': date(year, 6, 19), 'Independence Day': date(year, 7, 4),
             'Veterans Day': date(year, 11, 11), 'Christmas Day': date(year, 12, 25)}
    days = {_observed(d): name for name, d in fixed.items()}
    days.update({
        _nth_weekday(year, 1, 0, 3): 'Martin Luther King Jr. Day', _nth_weekday(year, 2, 0, 3): 'Presidents’ Day',
        _last_weekday(year, 5, 0): 'Memorial Day', _nth_weekday(year, 9, 0, 1): 'Labor Day',
        _nth_weekday(year, 10, 0, 2): 'Columbus Day', _nth_weekday(year, 11, 3, 4): 'Thanksgiving',
    })
    return days


def holiday(day):
    """The US federal holiday on this date, or None."""
    return holidays(day.year).get(day)


def day_type(when):
    """0 for a weekday, 1 for a weekend day or holiday (they ride like weekends)."""
    return 1 if when.weekday() >= 5 or holiday(when.date()) else 0


def hour_key(when):
    return when.strftime('%Y-%m-%dT%H')


def multiplier(model, temp_c, precip_mm, snow_cm, snow_72h_cm):
    """The fitted trip multiplier for an hour's weather, 1.0 without a fitted table."""
    table = model.get('weather')
    if not table:
        return 1.0
    s, h = sky(precip_mm, snow_cm), heat(temp_c)
    if s in ('dry', 'drizzle') and snow_72h_cm >= SNOW_AFTER_CM and table.get('after_snow'):
        return table['after_snow']
    return table['by_sky_heat'].get(f'{s}|{h}', table['by_sky'].get(s, 1.0))


def hour_factor(model, when):
    """Weather multiplier for `when` from the live conditions in `model` (see with_conditions)."""
    return model.get('live_factors', {}).get(hour_key(when), 1.0)


class Forecast:
    def __init__(self, hours):
        self.hours = hours  # 'YYYY-MM-DDTHH' -> (temp_c, precip_mm, snow_cm), New York time
        self._factors = {}  # computed once per weather table: the forecast is shared for 30 minutes

    @classmethod
    def parse(cls, body):
        hourly = body['hourly']
        return cls({t[:13]: (temp, precip or 0.0, snow or 0.0) for t, temp, precip, snow in
                    zip(hourly['time'], hourly['temperature_2m'], hourly['precipitation'], hourly['snowfall'])
                    if temp is not None})

    def snow_72h(self, when):
        return sum(self.hours.get(hour_key(when - timedelta(hours=h)), (0, 0, 0))[2] for h in range(1, 73))

    def factors(self, model):
        key = id(model.get('weather'))
        if key not in self._factors:
            out = {}
            for hour, (temp, precip, snow) in self.hours.items():
                when = datetime.strptime(hour, '%Y-%m-%dT%H')
                out[hour] = round(multiplier(model, temp, precip, snow, self.snow_72h(when)), 3)
            self._factors = {key: out}
        return self._factors[key]


_lock = threading.Lock()
_cache = {'at': None, 'forecast': None, 'failed_at': None}


def _fetch():
    with urllib.request.urlopen(FORECAST_URL, timeout=TIMEOUT_S) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('forecast too large')
    return Forecast.parse(json.loads(body))


def forecast():
    """The cached Open-Meteo forecast, refreshed past TTL_S; None when unavailable."""
    now = time.monotonic()
    with _lock:
        at, cached, failed = _cache['at'], _cache['forecast'], _cache['failed_at']
        fresh = at is not None and now - at < TTL_S
        cooling = failed is not None and now - failed < FAIL_COOLDOWN_S
    if fresh or cooling:
        return cached if at is not None and now - at < MAX_STALE_S else None
    try:
        result = _fetch()
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning('Weather forecast unavailable: %s', type(error).__name__)
        with _lock:
            _cache['failed_at'] = now
        return cached if at is not None and now - at < MAX_STALE_S else None
    with _lock:
        _cache.update(at=now, forecast=result, failed_at=None)
    return result


def reset_cache():
    """Forget the cached forecast (tests only)."""
    with _lock:
        _cache.update(at=None, forecast=None, failed_at=None)


def with_conditions(model, now, source=None):
    """The model plus live hourly factors, and a summary of this hour for answers."""
    day = holiday(now.date())
    current = (source or forecast)()
    summary = {'holiday': day, 'weather': None, 'factor': 1.0}
    if current is None:
        return {**model, 'live_factors': {}}, summary
    factors = current.factors(model)
    hour = current.hours.get(hour_key(now))
    if hour:
        temp, precip, snow = hour
        factor = factors[hour_key(now)]
        summary.update(factor=factor, weather={
            'sky': sky(precip, snow), 'temp_c': round(temp), 'precip_mm': precip, 'snow_cm': snow,
            'snow_72h_cm': round(current.snow_72h(now), 1),
        })
    return {**model, 'live_factors': factors}, summary


def describe(summary):
    """One sentence on why this hour differs from average, or '' when it does not."""
    parts = []
    weather = summary.get('weather')
    if weather:
        label = weather['sky'] if weather['sky'] != 'dry' else (
            'snow on the ground' if weather['snow_72h_cm'] >= SNOW_AFTER_CM else 'freezing' if weather['temp_c'] < 0 else '')
        if label:
            parts.append(f"{label[0].upper()}{label[1:]}, {weather['temp_c']}°C")
    if summary.get('holiday'):
        parts.append(summary['holiday'])
    factor = summary.get('factor', 1.0)
    if not parts and 0.9 <= factor <= 1.1:
        return ''
    effect = ('' if 0.9 <= factor <= 1.1 else
              f": about {round((1 - factor) * 100)}% fewer trips than usual, so refills are slower" if factor < 1
              else f": about {round((factor - 1) * 100)}% more trips than usual")
    return ' · '.join(parts) + effect + '.' if parts else ''
