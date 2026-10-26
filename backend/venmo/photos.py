"""Authenticated thumbnail bytes; upstream URLs are never browser image sources."""
from collections import OrderedDict
from threading import Lock
import base64
import time
from . import venmo_client
from .profiles import photo_url

cache = OrderedDict()
lock = Lock()


def thumbnail(profile, db=None):
    url = photo_url(profile.get('photoUrl'))
    if not profile.get('found') or not url:
        raise ValueError('No thumbnail')
    key = (profile['handle'], url)
    with lock:
        saved = cache.get(key)
        if saved and saved[0] > time.monotonic():
            return saved[1]
    result = None
    if db is not None:
        try:
            rows = db.table('venmo_photos').select('body,content_type').eq('handle', key[0]).eq('photo_url', url).execute().data
            if rows:
                # PostgREST transports the bounded thumbnail bytes as base64 text.
                body = base64.b64decode(rows[0]['body'], validate=True)
                if len(body) <= 512 * 1024 and rows[0]['content_type'] in {'image/jpeg', 'image/png', 'image/webp'}:
                    result = (body, rows[0]['content_type'])
        except Exception:
            pass
    if result is None:
        result = venmo_client.fetch(url, image=True, limit=512 * 1024, token_wait=1)
        if db is not None:
            try:
                db.table('venmo_photos').upsert(dict(handle=key[0], photo_url=url, body=base64.b64encode(result[0]).decode('ascii'), content_type=result[1])).execute()
            except Exception:
                pass
    with lock:
        cache[key] = (time.monotonic() + 86400, result)
        cache.move_to_end(key)
        while len(cache) > 100:
            cache.popitem(last=False)
    return result
