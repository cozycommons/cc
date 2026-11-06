"""Live Citi Bike dock availability from the public GBFS feed (no auth).

Station locations change rarely and status refreshes every minute. Feeds are
cached process-wide. Past its TTL a feed is still served while one background
thread refreshes it, so a request never waits on Citi Bike once the cache is
warm; only a cold start, or a feed older than MAX_STALE_S, fetches inline. One
attempt per fetch with a hard timeout; failures raise GbfsError without the
provider's response text, and a failed background refresh keeps the old copy.
After an inline fetch fails, requests fail fast for FAIL_COOLDOWN_S instead of
each waiting out the timeout: these routes share the API's worker threads, so a
Citi Bike outage must not hold them all.
"""
import json
import logging
import threading
import time
import urllib.request

from .wait import Dock

logger = logging.getLogger(__name__)

FEED = 'https://gbfs.lyft.com/gbfs/2.3/bkn/en/'
TTL_S = {'station_information': 3600.0, 'station_status': 60.0}
# Live counts older than this would mislead, so a request fetches inline instead.
MAX_STALE_S = {'station_information': 86400.0, 'station_status': 300.0}
TIMEOUT_S = 10
FAIL_COOLDOWN_S = 30.0
MAX_BYTES = 8_000_000

_lock = threading.Lock()
_cache = {}  # feed -> (fetched at, stations)
_refreshing = set()
_fetching = {feed: threading.Lock() for feed in TTL_S}
_failed = {}  # feed -> when its last inline fetch failed
_joined = (None, None, None)  # (info, status, docks): rebuilt only when a feed changes


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


def _store(feed):
    stations = _fetch(feed)
    with _lock:
        _cache[feed] = (time.monotonic(), stations)
    return stations


def _refresh(feed):
    try:
        _store(feed)
    except GbfsError as error:
        logger.warning('Citi Bike GBFS refresh failed: %s', error)
    finally:
        with _lock:
            _refreshing.discard(feed)


def start_refresh(feed):
    threading.Thread(target=_refresh, args=(feed,), name=f'gbfs-{feed}', daemon=True).start()


def _feed(feed):
    with _lock:
        cached = _cache.get(feed)
        age = time.monotonic() - cached[0] if cached else None
        if age is not None and age < MAX_STALE_S[feed]:
            if age >= TTL_S[feed] and feed not in _refreshing:
                _refreshing.add(feed)
                start_refresh(feed)
            return cached[1]
    # Cold or too stale: one request fetches; concurrent ones wait for it, then reuse
    # it, or fail fast if it failed.
    _fail_fast(feed)
    with _fetching[feed]:
        with _lock:
            cached = _cache.get(feed)
            if cached and time.monotonic() - cached[0] < MAX_STALE_S[feed]:
                return cached[1]
        _fail_fast(feed)
        try:
            return _store(feed)
        except GbfsError:
            with _lock:
                _failed[feed] = time.monotonic()
            raise


def _fail_fast(feed):
    with _lock:
        failed = _failed.get(feed)
    if failed is not None and time.monotonic() - failed < FAIL_COOLDOWN_S:
        raise GbfsError(f'{feed}: failed recently')


def status_age_s():
    """Seconds since station_status was fetched (0 before the first fetch)."""
    with _lock:
        cached = _cache.get('station_status')
    return time.monotonic() - cached[0] if cached else 0.0


def reset_cache():
    """Forget cached feeds (tests only)."""
    global _joined
    _cache.clear()
    _refreshing.clear()
    _failed.clear()
    _joined = (None, None, None)


def docks():
    global _joined
    info_feed, status_feed = _feed('station_information'), _feed('station_status')
    if _joined[0] is info_feed and _joined[1] is status_feed:
        return _joined[2]
    status = {s.get('station_id'): s for s in status_feed if isinstance(s, dict)}
    found = []
    for info in info_feed:
        # One malformed station is skipped, not a 500 on every route for an hour.
        try:
            live = status.get(info['station_id'])
            if not live or not live.get('is_installed'):
                continue
            found.append(Dock(str(info['short_name']), str(info['name']), float(info['lat']), float(info['lon']),
                              int(live.get('num_docks_available') or 0), bool(live.get('is_returning')),
                              int(live.get('num_bikes_available') or 0), bool(live.get('is_renting')),
                              int(live.get('num_ebikes_available') or 0), int(live.get('last_reported') or 0),
                              int(live.get('num_docks_disabled') or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    if not found:
        raise GbfsError('no installed stations')
    _joined = (info_feed, status_feed, found)
    return found
