"""Short-lived, handle-scoped thumbnail authorization for browser image requests."""
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

KEY = secrets.token_bytes(32)


def signature(handle, user, expires):
    return hmac.new(KEY, f'{handle}:{user}:{expires}'.encode(), hashlib.sha256).hexdigest()


def signed_path(handle, user):
    expires = int(time.time()) + 300
    return '/venmo/photo?' + urlencode(dict(handle=handle, user=user, expires=expires, sig=signature(handle, user, expires)))


def authorized(handle, user, expires, sig):
    return bool(user and sig and int(time.time()) <= expires <= int(time.time()) + 300
                and hmac.compare_digest(signature(handle, user, expires), sig))
