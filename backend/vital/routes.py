"""/vital: VITAL Brooklyn's live headcount next to its typical count for each weekday and hour.

The live count is cached for CACHE_S, so page polls never reach Safespace more
than once a minute per process. A failed fetch fails fast for FAIL_COOLDOWN_S:
these routes share the API's worker threads. The typical counts are the
committed week.json (busy.py --write).
"""
from datetime import datetime
from functools import lru_cache
import json
import threading
import time

from fastapi import APIRouter, HTTPException

from . import feed
from .busy import WEEK
from .recorder import NEW_YORK

router = APIRouter()

CACHE_S = 60.0
FAIL_COOLDOWN_S = 30.0

_lock = threading.Lock()
_live = None  # (fetched at, people)
_failed_at = 0.0


@lru_cache(maxsize=1)
def typical_week():
    return json.loads(WEEK.read_text())


def live_count(now):
    """Return (fetched at, people), fetching at most once per CACHE_S; raises FeedError."""
    global _live, _failed_at
    with _lock:
        if _live and now - _live[0] < CACHE_S:
            return _live
        if now - _failed_at < FAIL_COOLDOWN_S:
            raise feed.FeedError('cooling down')
        try:
            _live = (now, feed.fetch())
        except feed.FeedError:
            _failed_at = now
            raise
        return _live


@router.get('/week')
def week():
    return typical_week()


@router.get('/now')
def now():
    try:
        fetched, people = live_count(time.time())
    except feed.FeedError:
        raise HTTPException(503, 'The VITAL headcount is unavailable right now.') from None
    at = datetime.fromtimestamp(fetched, NEW_YORK)
    return {'people': people, 'at': at.isoformat(timespec='seconds'),
            'typical': typical_week()['hours'][at.weekday()][at.hour]}
