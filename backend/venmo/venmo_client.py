"""Bounded, cookie-free outbound requests with shared backpressure."""
import os
import time
from threading import Lock
import httpx


class Unavailable(Exception):
    pass


class TokenBucket:
    def __init__(self, rate=1, burst=5, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens, self.updated = float(burst), clock()
        self.lock = Lock()

    def wait(self, timeout):
        deadline = self.clock() + timeout
        while not self.take():
            remaining = deadline - self.clock()
            if remaining <= 0:
                return False
            time.sleep(min(.05, remaining))
        return True

    def take(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


class CircuitBreaker:
    def __init__(self, clock=time.monotonic):
        self.clock, self.failures, self.until, self.probing = clock, 0, 0, False
        self.lock = Lock()

    def enter(self):
        with self.lock:
            if self.failures < 5:
                return True
            if self.clock() < self.until or self.probing:
                return False
            self.probing = True
            return True

    def finish(self, success):
        with self.lock:
            self.probing = False
            self.failures = 0 if success else self.failures + 1
            if self.failures >= 5:
                self.until = self.clock() + 600


bucket = TokenBucket(float(os.getenv('VENMO_REQUEST_RATE', '1')), int(os.getenv('VENMO_REQUEST_BURST', '5')))
breaker = CircuitBreaker()


def fetch(url, *, limit=1_000_000, image=False, bypass_breaker=False, validate=None, token_wait=0):
    # Take a token before reserving the half-open probe: denied traffic cannot strand it.
    if not (bucket.wait(token_wait) if token_wait else bucket.take()) or (not bypass_breaker and not breaker.enter()):
        raise Unavailable('Venmo backoff')
    success = False
    try:
        deadline = time.monotonic() + 3
        with httpx.Client(timeout=3, follow_redirects=False, headers={
            'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*' if image else 'text/html',
        }) as client:
            with client.stream('GET', url) as response:
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if image and content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
                    raise ValueError('Unexpected image type')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit or time.monotonic() > deadline:
                        raise ValueError('Venmo response budget exceeded')
        result = validate(bytes(body)) if validate else (bytes(body), content_type)
        success = True
        return result
    finally:
        if not bypass_breaker:
            breaker.finish(success)
