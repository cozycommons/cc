"""Windowed, handle-scoped thumbnail authorization for browser image requests."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlencode

KEY = (os.getenv('VENMO_PHOTO_SIGNING_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or secrets.token_hex(32)).encode()

WINDOW = 21600


def version(photo_url):
    return hashlib.sha256(photo_url.encode()).hexdigest()[:16]


def signature(handle, user, expires, v=""):
    return hmac.new(KEY, f'{handle}:{user}:{expires}:{v}'.encode(), hashlib.sha256).hexdigest()


def signed_path(handle, user, photo_url=""):
    v = version(photo_url)
    expires = (int(time.time()) // WINDOW + 2) * WINDOW
    return '/venmo/photo?' + urlencode(dict(handle=handle, user=user, expires=expires, v=v, sig=signature(handle, user, expires, v)))


def authorized(handle, user, expires, sig, v=""):
    now = int(time.time())
    return bool(user and sig and now <= expires <= now + 2 * WINDOW
                and hmac.compare_digest(signature(handle, user, expires, v), sig))
