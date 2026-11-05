"""Live Citi Bike dock availability from the public GBFS feed (no auth).

Station locations change rarely and status refreshes every minute, so bodies
are cached process-wide for their feed's TTL and concurrent requests share one
fetch. One attempt per fetch with a hard timeout; failures raise GbfsError
without the provider's response text.
"""
import json
import threading
import time
import urllib.request

from .wait import Dock

FEED = 'https://gbfs.lyft.com/gbfs/2.3/bkn/en/'
TTL_S = {'station_information': 3600.0, 'station_status': 60.0}
TIMEOUT_S = 10
MAX_BYTES = 8_000_000

_lock = threading.Lock()
_cache = {}


class GbfsError(Exception):
    pass


def _fetch(feed):
    try:
        with urllib.request.urlopen(FEED + feed + '.json', timeout=TIMEOUT_S) as response:
            body = response.read(MAX_BYTES + 1)
    except OSError as error:
        raise GbfsError(f'{feed}: {type(error).__name__}') from None
    if len(body) > MAX_BYTES:
        raise GbfsError(f'{feed}: response too large')
    try:
        return json.loads(body)['data']['stations']
    except (ValueError, KeyError, TypeError):
        raise GbfsError(f'{feed}: unexpected response') from None


def _feed(feed):
    with _lock:
        cached = _cache.get(feed)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        stations = _fetch(feed)
        _cache[feed] = (time.monotonic() + TTL_S[feed], stations)
        return stations


def reset_cache():
    """Forget cached feeds (tests only)."""
    _cache.clear()


def docks():
    status = {s['station_id']: s for s in _feed('station_status')}
    found = []
    for info in _feed('station_information'):
        live = status.get(info['station_id'])
        if not live or not live.get('is_installed'):
            continue
        found.append(Dock(info['short_name'], info['name'], float(info['lat']), float(info['lon']),
                          int(live.get('num_docks_available', 0)), bool(live.get('is_returning'))))
    if not found:
        raise GbfsError('no installed stations')
    return found
