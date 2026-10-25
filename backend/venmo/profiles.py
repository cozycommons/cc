"""Best-effort public Venmo preview. Process-local, bounded, ephemeral cache only."""
import json
import time
from collections import OrderedDict, deque
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urlsplit

import httpx

from .usernames import normalize_username


def photo_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return value if (parsed.scheme == 'https' and parsed.netloc == 'pics-v3.venmo.com') else None


class ProfileHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.next_data = ''
        self.inside = False
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.inside = attrs.get('id') == '__NEXT_DATA__'
        if tag == 'meta' and attrs.get('property') in ('og:title', 'og:image'):
            self.meta[attrs['property']] = attrs.get('content', '')

    def handle_endtag(self, tag):
        if tag == 'script':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.next_data += data


def parse_profile(html, handle):
    parser = ProfileHTML()
    parser.feed(html)
    user = None
    try:
        user = json.loads(parser.next_data)['props']['pageProps']['user']
    except (ValueError, KeyError, TypeError):
        pass
    if isinstance(user, dict) and str(user.get('username', '')).lower() == handle.lower():
        name = user.get('displayName')
        name = name[:100] if isinstance(name, str) else handle
        initials = user.get('initials')
        return dict(handle=handle, displayName=name, photoUrl=photo_url(user.get('profilePictureUrl')),
                    initials=initials[:4] if isinstance(initials, str) else name[:1],
                    active=user.get('isActive') is not False)
    title = parser.meta.get('og:title', '')
    name, separator, username = title.rpartition(' | @')
    if separator and username.lower() == handle.lower() and name.strip():
        return dict(handle=handle, displayName=name.strip()[:100],
                    photoUrl=photo_url(parser.meta.get('og:image')), initials=name.strip()[:1], active=True)
    return None


class ProfileLookup:
    def __init__(self):
        self.cache = OrderedDict()
        self.users = OrderedDict()
        self.lock = Lock()

    def lookup(self, raw_handle, user_id):
        missing = {'found': False}
        try:
            handle = normalize_username(raw_handle)
            if not handle:
                return missing
            key = handle.lower()
            now = time.monotonic()
            with self.lock:
                cached = self.cache.get(key)
                if cached and cached[0] > now:
                    return cached[1]
                visits = self.users.setdefault(str(user_id), deque())
                while visits and visits[0] <= now - 60:
                    visits.popleft()
                if len(visits) >= 30:
                    return missing
                visits.append(now)
                self.users.move_to_end(str(user_id))
                while len(self.users) > 5000:
                    self.users.popitem(last=False)
            # Fresh client: no cookies, redirects disabled, bounded response body.
            deadline = time.monotonic() + 3
            with httpx.Client(timeout=3, follow_redirects=False, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept': 'text/html',
            }) as client:
                with client.stream('GET', f'https://account.venmo.com/u/{handle}') as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise TimeoutError('Profile deadline exceeded')
                        body.extend(chunk)
                        if len(body) > 1_000_000:
                            raise ValueError('Profile too large')
                    profile = parse_profile(body.decode('utf-8', errors='replace'), handle)
            result = {'found': True, **profile} if profile else missing
        except Exception:
            result = missing
        # Invalid input has no cache key.
        if 'key' in locals():
            with self.lock:
                self.cache[key] = (time.monotonic() + (86400 if result['found'] else 300), result)
                self.cache.move_to_end(key)
                while len(self.cache) > 2000:
                    self.cache.popitem(last=False)
        return result


lookup = ProfileLookup()
