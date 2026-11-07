"""Policy-free, stdlib GET gateway. No transaction or application imports.

The caller supplies storage, host classes, budgets, TTL and validation. SQLite
serializes token/budget reservations; advisory file locks coalesce cache fills
across threads and processes. Network IO never holds a SQLite transaction.
"""
from __future__ import annotations

import contextlib
import copy
import threading
from concurrent.futures import Future
import fcntl
import gzip
import hashlib
import io
import http.client
import math
import json
import os
import random
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


class GatewayError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class AuthRejected(GatewayError):
    pass


class CircuitOpen(GatewayError):
    pass


class BudgetExceeded(GatewayError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def request_key(url, headers):
    """Normalize query order, retain repeated params and isolate credentials."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)))
    url = urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ''))
    headers = {k.lower(): v for k, v in headers.items()}
    for name, value in headers.items():
        if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
            try:
                headers[name] = json.dumps(json.loads(value), sort_keys=True, separators=(',', ':'))
            except (ValueError, TypeError):
                pass
    return digest(json.dumps([url, sorted(headers.items())], separators=(',', ':')))


class ReadGateway:
    def __init__(self, directory, *, limits, daily_budget, clock=time.time, sleep=time.sleep,
                 jitter=random.uniform, day_key=None, critical_reserve=0, host_policies=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / 'reads.sqlite3'
        self.limits, self.daily_budget = limits, daily_budget
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.critical_reserve = critical_reserve
        self.day_key = day_key
        # Optional per-host limits on top of the shared budget: {'budget': GETs per day,
        # 'jitter': extra seconds added after each GET, 'trip_after': consecutive
        # failures before a 'trip_seconds' cooldown}.
        self.host_policies = host_policies or {}
        self._flights_lock = threading.Lock()
        self._flights = {}
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body BLOB NOT NULL, expires REAL, scope TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS hosts (host TEXT PRIMARY KEY, tokens REAL, updated REAL,
                    blocked REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS auth (scope TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS epochs (scope TEXT PRIMARY KEY, epoch INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS counters (day TEXT, endpoint TEXT, metric TEXT, count INTEGER,
                    PRIMARY KEY(day,endpoint,metric));
                CREATE TABLE IF NOT EXISTS host_counters (day TEXT, host TEXT, count INTEGER, PRIMARY KEY(day,host));
            ''')
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            yield db
        finally:
            db.close()

    def _day(self):
        return self.day_key(self.clock()) if self.day_key else datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()

    def _count(self, db, endpoint, metric):
        db.execute('INSERT INTO counters VALUES(?,?,?,1) ON CONFLICT(day,endpoint,metric) '
                   'DO UPDATE SET count=count+1', (self._day(), endpoint, metric))

    def stats(self):
        with self._db() as db:
            rows = db.execute('SELECT endpoint,metric,count FROM counters WHERE day=?', (self._day(),)).fetchall()
            auth = db.execute('SELECT count(*) FROM auth').fetchone()[0]
            hosts = db.execute('SELECT host,blocked,failures FROM hosts WHERE blocked>?', (self.clock(),)).fetchall()
            per_host = dict(db.execute('SELECT host,count FROM host_counters WHERE day=?', (self._day(),)).fetchall())
        endpoints = {}
        for endpoint, metric, count in rows:
            endpoints.setdefault(endpoint, {})[metric] = count
        return {'day': self._day(), 'budget': self.daily_budget,
                'requests': sum(v.get('network', 0) for v in endpoints.values()),
                'endpoints': endpoints, 'auth_latches': auth,
                'hosts': {h: {'requests': per_host.get(h, 0), 'budget': p['budget']}
                          for h, p in self.host_policies.items() if 'budget' in p},
                'circuits': [{'host': h, 'until': b, 'failures': f} for h, b, f in hosts]}

    def peek(self, url, headers=None):
        headers = dict(headers or {})
        headers['Accept-Encoding'] = 'gzip'
        with self._db() as db:
            row = db.execute('SELECT body,expires FROM cache WHERE key=?',
                             (digest(request_key(url, headers)),)).fetchone()
        if row and (row[1] is None or row[1] > self.clock()):
            return json.loads(row[0])
        return None

    def epoch(self, scope):
        with self._db() as db:
            row = db.execute('SELECT epoch FROM epochs WHERE scope=?', (scope,)).fetchone()
        return row[0] if row else 0

    def invalidate(self, scope):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO epochs VALUES(?,1) ON CONFLICT(scope) DO UPDATE SET epoch=epoch+1', (scope,))
            db.execute('DELETE FROM cache WHERE scope=?', (scope,))
            db.commit()

    def latch_auth(self, scope):
        if scope:
            with self._db() as db:
                db.execute('INSERT OR IGNORE INTO auth VALUES(?)', (scope,))

    def _check_auth(self, db, scope):
        if scope and db.execute('SELECT 1 FROM auth WHERE scope=?', (scope,)).fetchone():
            raise AuthRejected('Credentials rejected; reconnect with changed credentials', 401)

    def _reserve(self, host, endpoint, scope, critical=False):
        rate, capacity = self.limits[host]
        policy = self.host_policies.get(host, {})
        while True:
            now = self.clock()
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    self._check_auth(db, scope)
                    row = db.execute('SELECT tokens,updated,blocked FROM hosts WHERE host=?', (host,)).fetchone()
                    tokens, updated, blocked = row or (capacity, now, 0)
                    if blocked > now:
                        raise CircuitOpen('Read circuit cooling down', 503)
                    used = db.execute("SELECT coalesce(sum(count),0) FROM counters WHERE day=? AND metric='network'", (self._day(),)).fetchone()[0]
                    if used >= self.daily_budget + (self.critical_reserve if critical else 0):
                        raise BudgetExceeded('Daily read budget exhausted')
                    if 'budget' in policy:
                        row = db.execute('SELECT count FROM host_counters WHERE day=? AND host=?', (self._day(), host)).fetchone()
                        if (row[0] if row else 0) >= policy['budget']:
                            raise BudgetExceeded(f'Daily {host} read budget exhausted')
                    tokens = min(capacity, tokens + max(0, now-updated)*rate) if rate else capacity
                    wait = max(0, (1-tokens)/rate) if rate else 0
                    if wait == 0:
                        # Jitter spends extra tokens, so the next GET on this host waits longer.
                        spent = 1 + (self.jitter(0, policy['jitter'])*rate if policy.get('jitter') else 0)
                        db.execute('INSERT INTO hosts(host,tokens,updated) VALUES(?,?,?) ON CONFLICT(host) '
                                   'DO UPDATE SET tokens=excluded.tokens,updated=excluded.updated', (host, tokens-spent, now))
                        self._count(db, endpoint, 'network')
                        if 'budget' in policy:
                            db.execute('INSERT INTO host_counters VALUES(?,?,1) ON CONFLICT(day,host) '
                                       'DO UPDATE SET count=count+1', (self._day(), host))
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            if wait == 0:
                return
            self.sleep(wait)

    def _failure(self, host, status, retry_after=None):
        if status != 429 and not (status and 500 <= status < 600):
            return
        now = self.clock()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            failures = db.execute('SELECT failures FROM hosts WHERE host=?', (host,)).fetchone()[0] + 1
            # Bound malformed/untrusted Retry-After values; backoff stays capped.
            delay = self.jitter(1, min(300, 2**min(failures+1, 9)))
            policy = self.host_policies.get(host, {})
            if policy.get('trip_after') and failures >= policy['trip_after']:
                delay = max(delay, policy['trip_seconds'])
            if retry_after:
                try:
                    value = float(retry_after)
                    delay = max(delay, min(3600, max(0, value)) if math.isfinite(value) else 3600)
                except ValueError:
                    try:
                        delay = max(delay, min(3600, max(0, parsedate_to_datetime(retry_after).timestamp()-now)))
                    except (ValueError, TypeError, OverflowError):
                        pass
            db.execute('UPDATE hosts SET blocked=max(blocked,?),failures=? WHERE host=?', (now+delay, failures, host))
            db.commit()

    def get(self, url, **kwargs):
        # A refresh may not join a fill that started before it.
        if kwargs.get('fresh') or kwargs.get('refresh'):
            return self._get(url, **kwargs)
        scope = kwargs.get('scope', '')
        key = digest(request_key(url, kwargs.get('headers') or {}) + scope +
                     str(self.epoch(scope)) + kwargs.get('result_type', 'json'))
        with self._flights_lock:
            future = self._flights.get(key)
            leader = future is None
            if leader:
                future = self._flights[key] = Future()
        if not leader:
            with self._db() as db:
                self._count(db, kwargs['endpoint'], 'calls')
                self._count(db, kwargs['endpoint'], 'coalesced')
            result = copy.deepcopy(future.result())
            if kwargs.get('validate'):
                kwargs['validate'](result)
            return result
        try:
            result = self._get(url, **kwargs)
            future.set_result(result)
            return copy.deepcopy(result)
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self._flights_lock:
                self._flights.pop(key, None)

    def _get(self, url, *, headers=None, host, endpoint, ttl=60, scope='', fresh=False, refresh=False,
            timeout=30, opener=None, decode=json.loads, validate=None, auth_body=None, critical=False, result_type='json', max_bytes=16*1024*1024):
        """One GET attempt, coalesced/cached unless fresh. No automatic replay.

        ttl may be seconds, None (permanent), or a callback on decoded data.
        Auth and circuit/budget errors fail closed; cached auth data is never
        returned after its credentials have been latched. A fresh request always
        performs IO and bypasses both the cached body and the fill lock.
        A refresh rereads any expiring entry under the fill lock and stores the
        result, so later cached readers see it; permanent entries still hit.
        """
        headers = dict(headers or {})
        headers['Accept-Encoding'] = 'gzip'
        key = digest(request_key(url, headers) + scope)
        # A bounded set of stripes avoids unsafe unlinking of active flock files.
        lock_path = self.directory / ('fill-' + key[:2] + '.lock')
        with self._db() as db:
            self._check_auth(db, scope)
            self._count(db, endpoint, 'calls')
        # flock is independently acquired on each open, including other threads.
        with contextlib.ExitStack() as stack:
            if not fresh:
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                stream = stack.enter_context(os.fdopen(fd, 'r+'))
                fcntl.flock(stream, fcntl.LOCK_EX)
                with self._db() as db:
                    self._check_auth(db, scope)
                    row = db.execute('SELECT body,expires FROM cache WHERE key=?', (key,)).fetchone()
                    if row and (row[1] is None or not refresh and row[1] > self.clock()):
                        self._count(db, endpoint, 'cache_hit')
                        data = decode(row[0])
                        if validate:
                            validate(data)
                        return data
            generation = self.epoch(scope)
            self._reserve(host, endpoint, scope, critical)
            request = urllib.request.Request(url, headers=headers, method='GET')
            try:
                with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                    raw = response.read(max_bytes+1)
                    if len(raw) > max_bytes:
                        raise GatewayError('Read response exceeds size limit')
                    response_headers = getattr(response, 'headers', {})
                    if response_headers.get('Content-Encoding', '').lower() == 'gzip':
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                            raw = compressed.read(max_bytes+1)
                        if len(raw) > max_bytes:
                            raise GatewayError('Decoded response exceeds size limit')
                try:
                    data = decode(raw)
                except (ValueError, UnicodeError) as error:
                    if scope and auth_body and auth_body(raw):
                        self.latch_auth(scope)
                        raise AuthRejected('Credentials rejected; reconnect') from error
                    raise GatewayError('Read returned non-JSON') from error
                if validate:
                    validate(data)
            except urllib.error.HTTPError as error:
                with self._db() as db:
                    self._count(db, endpoint, 'error')
                if scope and error.code in (401, 403):
                    self.latch_auth(scope)
                    raise AuthRejected('Credentials rejected; reconnect', error.code) from error
                self._failure(host, error.code, (error.headers or {}).get('Retry-After'))
                raise GatewayError(f'HTTP {error.code}', error.code) from error
            except (OSError, http.client.HTTPException, EOFError, zlib.error) as error:
                self._failure(host, 503)
                with self._db() as db:
                    self._count(db, endpoint, 'error')
                raise GatewayError('Read network error') from error
            duration = ttl(data) if callable(ttl) else ttl
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT epoch FROM epochs WHERE scope=?', (scope,)).fetchone()
                unchanged = generation == (row[0] if row else 0)
                db.execute('UPDATE hosts SET blocked=0,failures=0 WHERE host=? AND blocked<=?', (host, self.clock()))
                if not fresh and unchanged and (duration is None or duration > 0):
                    db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)',
                               (key, raw, None if duration is None else self.clock()+duration, scope))
                # Bounded expired cache; permanent entries are deliberately retained.
                db.execute('DELETE FROM cache WHERE expires IS NOT NULL AND expires<?', (self.clock()-86400,))
                db.commit()
            return data
