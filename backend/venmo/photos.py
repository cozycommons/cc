"""Authenticated thumbnail bytes; upstream URLs are never browser image sources."""
from collections import OrderedDict
from threading import Lock
import time
from . import venmo_client
from .profiles import photo_url

cache = OrderedDict()
lock = Lock()


def thumbnail(profile):
    url = photo_url(profile.get('photoUrl'))
    if not profile.get('found') or not url:
        raise ValueError('No thumbnail')
    with lock:
        saved = cache.get(url)
        if saved and saved[0] > time.monotonic():
            return saved[1]
    result = venmo_client.fetch(url, image=True, limit=512 * 1024)
    with lock:
        cache[url] = (time.monotonic() + 86400, result)
        cache.move_to_end(url)
        while len(cache) > 100:
            cache.popitem(last=False)
    return result
