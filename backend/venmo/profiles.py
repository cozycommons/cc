"""Strict layered previews and durable last-known-good, with stale revalidation."""
import json
import random
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urlsplit, urlunsplit, urlencode
from .usernames import normalize_username
from . import venmo_client


def photo_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.netloc != 'pics-v3.venmo.com' or not parsed.path.startswith('/'):
            return None
        return urlunsplit(('https', parsed.netloc, parsed.path, urlencode({'width': 200, 'height': 200}), ''))
    except ValueError:
        return None


class ProfileHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.next_data, self.inside, self.meta = '', False, {}

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


def validate_user(user, handle):
    required = {'username': str, 'displayName': str, 'profilePictureUrl': str, 'initials': str, 'isActive': bool}
    errors = [key for key, kind in required.items() if not isinstance(user.get(key), kind)] if isinstance(user, dict) else list(required)
    if errors:
        raise ValueError(','.join(errors))
    if user['username'].lower() != handle.lower():
        raise ValueError('username mismatch')
    if not user['displayName'].strip() or len(user['displayName']) > 100:
        raise ValueError('displayName empty/long')
    if not user['initials'].strip() or len(user['initials']) > 4:
        raise ValueError('initials empty/long')
    photo = photo_url(user['profilePictureUrl'])
    if not photo:
        raise ValueError('profilePictureUrl host')
    return dict(handle=handle.lower(), displayName=user['displayName'].strip(), photoUrl=photo,
                initials=user['initials'], active=user['isActive'])


def parse_layers(html, handle):
    parser = ProfileHTML()
    parser.feed(html)
    failures = {}
    try:
        user = json.loads(parser.next_data)
        path = []
        for key in ('props', 'pageProps', 'user'):
            path.append(key)
            if not isinstance(user, dict) or key not in user:
                raise ValueError('.'.join(path) + ' missing/mistyped')
            user = user[key]
        if not isinstance(user, dict):
            raise ValueError('props.pageProps.user mistyped')
        return {**validate_user(user, handle), 'source': 'live'}, failures
    except (ValueError, KeyError, TypeError) as error:
        failures['next'] = str(error) if isinstance(error, KeyError) else 'invalid JSON or user fields' if isinstance(error, json.JSONDecodeError) else str(error)
    try:
        name, separator, username = parser.meta.get('og:title', '').rpartition(' | @')
        if not separator:
            raise ValueError('og:title missing/mistyped')
        user = dict(username=username, displayName=name, profilePictureUrl=parser.meta.get('og:image'), initials=name.strip()[:1], isActive=True)
        return {**validate_user(user, handle), 'source': 'og'}, failures
    except ValueError as error:
        failures['og'] = str(error)
    return None, failures


def parse_profile(html, handle):
    return parse_layers(html, handle)[0]


def ttl(found):
    return (86400 if found else 3600) * random.uniform(.9, 1.1)


class ProfileLookup:
    def __init__(self):
        self.cache, self.users, self.pending = OrderedDict(), OrderedDict(), set()
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='venmo')

    def load(self, db, handle):
        if db is None:
            return None
        rows = db.table('venmo_profiles').select('*').eq('handle', handle).execute().data
        if not rows:
            return None
        row = rows[0]
        try:
            profile = validate_user(dict(username=row['handle'], displayName=row['display_name'], profilePictureUrl=row['photo_url'], initials=row['initials'], isActive=row['active']), handle)
            return {**profile, 'source': 'cached', 'found': True, 'stale': True}
        except (ValueError, KeyError):
            return None

    def refresh(self, handle, db):
        result = None
        try:
            def parsed(body):
                profile = parse_profile(body.decode('utf-8', errors='replace'), handle)
                if not profile:
                    raise ValueError('No validated Venmo profile')
                return profile
            profile = venmo_client.fetch(f'https://account.venmo.com/u/{handle}', validate=parsed)
            result = {**profile, 'found': True, 'stale': False}
            if db is not None:
                db.table('venmo_profiles').upsert(dict(handle=handle, display_name=profile['displayName'], photo_url=profile['photoUrl'], initials=profile['initials'], active=profile['active'], source=profile['source'], fetched_at=datetime.now(timezone.utc).isoformat())).execute()
        except Exception:
            pass  # Optional preview must not interrupt payments.
        if result is not None:
            try:
                from .photos import thumbnail
                thumbnail(result, db)
            except Exception:
                pass
        with self.lock:
            previous = self.cache.get(handle)
            if result is None:
                result = {**previous[1], 'source': 'cached', 'stale': True} if previous and previous[1].get('found') else {'found': False}
            self.cache[handle] = (time.monotonic() + ttl(result.get('found', False) and not result.get('stale')), result)
            self.cache.move_to_end(handle)
            while len(self.cache) > 2000:
                self.cache.popitem(last=False)
            self.pending.discard(handle)
        return result

    def lookup(self, raw_handle, user_id, db=None):
        try:
            handle = normalize_username(raw_handle)
        except ValueError:
            return {'found': False}
        if not handle:
            return {'found': False}
        handle = handle.lower()
        now = time.monotonic()
        with self.lock:
            visits = self.users.setdefault(str(user_id), deque())
            while visits and visits[0] <= now - 60:
                visits.popleft()
            cached = self.cache.get(handle)
            if len(visits) >= 30:
                return cached[1] if cached else {'found': False}
            visits.append(now)
            self.users.move_to_end(str(user_id))
            while len(self.users) > 5000:
                self.users.popitem(last=False)
            if cached and cached[0] > now:
                return cached[1]
        try:
            stored = self.load(db, handle)
        except Exception:
            stored = None
        stale = stored or ({**cached[1], 'source': 'cached', 'stale': True} if cached and cached[1].get('found') else None)
        with self.lock:
            if handle in self.pending or len(self.pending) >= 32:
                return stale or {'found': False}
            self.pending.add(handle)
            if stale:
                self.cache[handle] = (now, stale)
        if stale:
            self.executor.submit(self.refresh, handle, db)
            return stale
        return self.refresh(handle, db)


lookup = ProfileLookup()
