"""Short-lived, handle-scoped thumbnail authorization for browser image requests."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlencode

KEY = (os.getenv('VENMO_PHOTO_SIGNING_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or secrets.token_hex(32)).encode()


def signature(handle, user, expires):
    return hmac.new(KEY, f'{handle}:{user}:{expires}'.encode(), hashlib.sha256).hexdigest()


def signed_path(handle, user):
    expires = int(time.time()) + 300
    return '/venmo/photo?' + urlencode(dict(handle=handle, user=user, expires=expires, sig=signature(handle, user, expires)))


def authorized(handle, user, expires, sig):
    return bool(user and sig and int(time.time()) <= expires <= int(time.time()) + 300
                and hmac.compare_digest(signature(handle, user, expires), sig))
