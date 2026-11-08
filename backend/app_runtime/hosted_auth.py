"""PKCE browser sign-in and host-bound sessions. No tokens are persisted.

Supabase access tokens stay in bounded process memory; cookies/tickets contain
only random references. Restart signs browsers out. No refresh tokens are kept.
"""
import base64
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

SESSION = '__Host-commons-session'
LOGIN = '__Host-commons-login'
CALLER = 'x-commons-apps-caller'
CALLER_REJECTED = 'Apps caller not recognized'
BROWSER_HEADERS = {
    'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; img-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


class Budget:
    """Bound unauthenticated allocation and Auth API work on a small VPS."""
    def __init__(self, maximum):
        self.maximum = maximum
        self.lock = threading.Lock()
        self.window, self.count = 0, 0

    def take(self):
        with self.lock:
            window = int(time.monotonic() // 60)
            if window != self.window:
                self.window, self.count = window, 0
            if self.count >= self.maximum:
                raise HTTPException(429, 'Sign-in is busy; retry shortly', headers={'Retry-After': '60'})
            self.count += 1


class Ephemeral:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}

    def put(self, value, ttl):
        with self.lock:
            now = time.monotonic()
            self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
            if len(self.entries) >= 4096:
                raise HTTPException(429, 'Too many sign-in sessions; retry later')
            key = secrets.token_urlsafe(32)
            self.entries[key] = (now + ttl, value)
            return key

    def delete_where(self, predicate):
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if not predicate(v[1])}

    def get(self, key, consume=False):
        with self.lock:
            entry = self.entries.pop(key, None) if consume else self.entries.get(key)
            if entry and entry[0] > time.monotonic():
                return entry[1]
        return None


def cookie(response, name, value, ttl):
    response.set_cookie(name, value, max_age=ttl, secure=True, httponly=True, samesite='lax', path='/')
    return response


def clean_cookie(raw):
    # Remove all platform cookies, including duplicate and malformed values.
    return '; '.join(part.strip() for part in raw.split(';')
                     if '=' in part and not part.strip().split('=', 1)[0].startswith('__Host-commons-'))


class HostedAuth:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.pending, self.sessions, self.tickets = Ephemeral(), Ephemeral(), Ephemeral()
        self.families = Ephemeral()
        self.login_budget, self.auth_budget = Budget(60), Budget(600)
        self.auth_slots = threading.BoundedSemaphore(4)

    def new_session(self, host, token, family=None):
        if family is None:
            family = self.families.put(True, 3600)
        if not self.families.get(family):
            raise HTTPException(401, 'Sign-in expired')
        return self.sessions.put({'host': host, 'token': token, 'family': family}, 3600)

    def user(self, token):
        if not token or len(token) > 16384:
            return None
        self.auth_budget.take()
        if not self.auth_slots.acquire(blocking=False):
            raise HTTPException(503, 'Sign-in is busy; retry shortly')
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                result = client.get(self.settings.supabase_url + '/auth/v1/user', headers={
                    'apikey': self.settings.publishable_key, 'Authorization': 'Bearer ' + token})
            if result.status_code != 200:
                return None
            data = result.json()
            if data.get('is_anonymous') or data.get('role') != 'authenticated':
                return None
            user_id = str(UUID(data['id']))
            # Decode only AFTER Auth has validated this exact access token. No
            # unverified claim or user_metadata can establish identity/access.
            encoded = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            if (claims.get('sub') != user_id or claims.get('iss') != self.settings.supabase_url + '/auth/v1'
                    or claims.get('aud') != 'authenticated' or claims.get('role') != 'authenticated'):
                return None
            client_id = claims.get('client_id')
            if client_id is not None and client_id != self.settings.mcp_client_id:
                return None
            return user_id
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return None
        finally:
            self.auth_slots.release()

    def can_create(self, token, user_id):
        # Reuse the authoritative Commons admin check on every allocation.
        # No service-role key or cached role/UUID allowlist enters the manager.
        self.auth_budget.take()
        if not self.auth_slots.acquire(blocking=False):
            raise HTTPException(503, 'Admin check is busy; retry shortly')
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                result = client.get('https://api.' + self.settings.domain + '/admin/session',
                                    headers={'Authorization': 'Bearer ' + token})
            data = result.json() if result.status_code == 200 else None
            return isinstance(data, dict) and data.get('id') == user_id
        except (httpx.HTTPError, ValueError, TypeError):
            return False
        finally:
            self.auth_slots.release()

    def host(self, request):
        # Never trust forwarded host headers from app containers or browsers.
        host = request.headers.get('host', '')
        if host == self.settings.portal:
            return host
        from .core import hostname
        for record in self.store.all():
            for service in record['routes']:
                if host == hostname(record['name'], service, self.settings):
                    return host
        raise HTTPException(400, 'Unknown app host')

    def app_of(self, url):
        """The app whose host serves url, or None for any other origin."""
        parsed, suffix = urlsplit(url), '.' + self.settings.domain
        host = parsed.hostname or ''
        label = host[:-len(suffix)] if host.endswith(suffix) else ''
        if parsed.scheme != 'https' or not label or '.' in label:
            return None
        return label.split('--')[0]

    def same_app(self, request, app):
        """Refuse requests another app's page started with this app's cookie.

        Sibling app hosts are one site, so SameSite=Lax still attaches a member's
        session to fetches, WebSockets, subresources and frames they trigger.
        Top-level navigations stay allowed: the other page cannot read them.
        """
        origin = request.headers.get('origin')
        if origin is not None:
            return self.app_of(origin) == app
        site = request.headers.get('sec-fetch-site')
        if site in {'same-origin', 'none'}:
            return True
        framed = request.headers.get('sec-fetch-dest') in {'iframe', 'frame', 'embed', 'object'}
        if site is not None and request.headers.get('sec-fetch-mode') == 'navigate' and not framed:
            return True
        # Cross-origin subresources and frames, or a browser without Fetch
        # Metadata: only a referring page on this app can vouch for them.
        referer = request.headers.get('referer')
        return referer is not None and self.app_of(referer) == app

    def session(self, request):
        host = self.host(request)
        entry = self.sessions.get(request.cookies.get(SESSION, ''))
        return entry if entry and entry['host'] == host and self.families.get(entry['family']) else None

    def identify(self, request):
        header = request.headers.get('authorization', '')
        if header.startswith('Bearer '):
            # Agent bearers arrive only through the Commons backend. Requiring
            # its shared secret keeps a user token leaked elsewhere (such as a
            # frontend session) from reaching shell or membership APIs.
            caller = request.headers.get(CALLER, '').encode()
            if not secrets.compare_digest(caller, self.settings.caller_secret.encode()):
                raise HTTPException(401, CALLER_REJECTED)
            return self.user(header[7:])
        # Browser cookies never authorize shell, membership or lifecycle APIs.
        if request.url.path == '/' or request.url.path.startswith('/authorize/'):
            entry = self.session(request)
            return self.user(entry['token']) if entry else None
        return None

    def install(self, app):
        @app.get('/_commons/login')
        def login(request: Request, app_state: str | None = None):
            self.login_budget.take()
            host = self.host(request)
            if host != self.settings.portal:
                state = self.pending.put({'host': host}, 300)
                url = self.settings.url(self.settings.portal) + '/_commons/authorize?' + urlencode({'target': host, 'state': state})
                return cookie(RedirectResponse(url, headers=BROWSER_HEADERS), LOGIN, state, 300)
            if app_state is not None:
                if len(app_state) > 128:
                    raise HTTPException(400, 'Sign-in expired; reopen the app')
                continuation = self.pending.get(app_state)
                if not continuation or not continuation.get('host'):
                    raise HTTPException(400, 'Sign-in expired; reopen the app')
            verifier = secrets.token_urlsafe(48)
            state = self.pending.put({'verifier': verifier, 'app_state': app_state}, 300)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            url = self.settings.supabase_url + '/auth/v1/authorize?' + urlencode({
                'provider': 'google', 'redirect_to': self.settings.url(host) + '/_commons/callback',
                'code_challenge': challenge, 'code_challenge_method': 's256'})
            return cookie(RedirectResponse(url, headers=BROWSER_HEADERS), LOGIN, state, 300)

        @app.get('/_commons/callback')
        def callback(request: Request, code: str = ''):
            if self.host(request) != self.settings.portal or not code or len(code) > 4096:
                raise HTTPException(400, 'Invalid sign-in callback')
            pending = self.pending.get(request.cookies.get(LOGIN, ''), consume=True)
            if not pending or 'verifier' not in pending:
                raise HTTPException(400, 'Sign-in expired; start again')
            try:
                with httpx.Client(timeout=10, follow_redirects=False) as client:
                    result = client.post(self.settings.supabase_url + '/auth/v1/token?grant_type=pkce',
                        headers={'apikey': self.settings.publishable_key},
                        json={'auth_code': code, 'code_verifier': pending['verifier']})
                result.raise_for_status()
                token = result.json()['access_token']
                if not self.user(token):
                    raise ValueError('Invalid user')
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise HTTPException(401, 'Sign-in failed; start again') from None
            session = self.new_session(self.settings.portal, token)
            destination = '/'
            app_state = pending.get('app_state')
            continuation = self.pending.get(app_state) if isinstance(app_state, str) else None
            if continuation and continuation.get('host'):
                destination = '/_commons/authorize?' + urlencode({
                    'target': continuation['host'], 'state': app_state,
                })
            response = cookie(RedirectResponse(destination, status_code=303, headers=BROWSER_HEADERS), SESSION, session, 3600)
            response.delete_cookie(LOGIN, path='/', secure=True, httponly=True, samesite='lax')
            return response

        @app.get('/_commons/authorize')
        def authorize(request: Request, target: str, state: str):
            if self.host(request) != self.settings.portal:
                raise HTTPException(400, 'Use the Apps sign-in page')
            pending = self.pending.get(state)
            if not pending or pending.get('host') != target:
                raise HTTPException(400, 'Sign-in expired; reopen the app')
            session = self.session(request)
            if not session or not self.user(session['token']):
                return RedirectResponse('/_commons/login?' + urlencode({'app_state': state}), headers=BROWSER_HEADERS)
            ticket = self.tickets.put({'host': target, 'state': state, 'token': session['token'], 'family': session['family']}, 60)
            return RedirectResponse(self.settings.url(target) + '/_commons/finish#' + ticket, headers=BROWSER_HEADERS)

        @app.get('/_commons/finish', response_class=HTMLResponse)
        def finish(request: Request):
            self.host(request)
            return HTMLResponse('<!doctype html><title>Opening app</title><p id="status">Opening app…</p><script src="/_commons/finish.js"></script>', headers=BROWSER_HEADERS)

        @app.get('/_commons/finish.js')
        def finish_js():
            return Response("""const ticket = location.hash.slice(1);
history.replaceState(null, '', '/_commons/finish');
fetch('/_commons/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ticket})})
.then(r => { if (!r.ok) throw Error(); location.replace('/'); })
.catch(() => { document.getElementById('status').textContent = 'Sign-in expired. Reopen the app from the Apps directory.'; });
""", media_type='text/javascript', headers=BROWSER_HEADERS)

        @app.post('/_commons/session')
        async def session(request: Request):
            host = self.host(request)
            if request.headers.get('origin') != self.settings.url(host):
                raise HTTPException(403, 'Origin denied')
            raw = b''
            async for chunk in request.stream():
                raw += chunk
                if len(raw) > 1024:
                    raise HTTPException(413, 'Request too large')
            import json
            try:
                ticket_id = json.loads(raw)['ticket']
                if not isinstance(ticket_id, str):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise HTTPException(400, 'Invalid sign-in') from None
            entry = self.tickets.get(ticket_id, consume=True)
            state = request.cookies.get(LOGIN, '')
            if not entry or entry['host'] != host or not secrets.compare_digest(entry['state'], state):
                raise HTTPException(401, 'Sign-in expired')
            if not self.pending.get(state, consume=True):
                raise HTTPException(401, 'Sign-in expired')
            # The next authorized request revalidates the upstream token.
            key = self.new_session(host, entry['token'], entry['family'])
            response = cookie(Response(status_code=204, headers=BROWSER_HEADERS), SESSION, key, 3600)
            response.delete_cookie(LOGIN, path='/', secure=True, httponly=True, samesite='lax')
            return response

        @app.post('/_commons/logout')
        def logout(request: Request):
            host = self.host(request)
            if request.headers.get('origin') != self.settings.url(host):
                raise HTTPException(403, 'Origin denied')
            key = request.cookies.get(SESSION, '')
            session = self.session(request)
            if session:
                self.sessions.get(key, consume=True)
            if session and host == self.settings.portal:
                family = session['family']
                # Live family checks also reject a ticket/session issued by an
                # in-flight request after this deletion. Snapshot deletion alone
                # would race a slow upstream user verification.
                self.families.get(family, consume=True)
                self.sessions.delete_where(lambda entry: entry.get('family') == family)
                self.tickets.delete_where(lambda entry: entry.get('family') == family)
            response = Response(status_code=204, headers=BROWSER_HEADERS)
            response.delete_cookie(SESSION, path='/', secure=True, httponly=True, samesite='lax')
            return response
