#!/usr/bin/env python3
"""Real DCR + PKCE + Streamable HTTP exercise, exclusively on loopback Supabase.

Run with backend/.venv/bin/python. Requires the configured loopback app and OAuth
client described in docs/mcp/README.md. Approve consent in the opened browser
using a synthetic local account with --interactive. By default consent is unattended.
Tokens stay in memory; never print credentials.
LOCAL_SUPABASE_SERVICE_ROLE_KEY is read only after both URL guards pass.
"""
import argparse
import asyncio
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import json
import os
from html.parser import HTMLParser
import secrets
import re
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit, urljoin
from uuid import uuid4
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def loopback(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Only HTTP loopback URLs are allowed.')
    return value.rstrip('/')


# The serving process routes Beli API calls here (scripts/commons-connector-local.sh).
FAKE_BELI = ('127.0.0.1', 8766)
BISTRO = {'id': 501, 'name': 'Synthetic Bistro', 'neighborhood': 'West Village', 'city': 'New York',
          'businesshours_set': [], 'reservation_platforms': {}}


def fake_beli():
    """Minimal synthetic Beli API: logins, trending, search and bookmarks. Records every save."""
    state = {'sessions': {}, 'saved': []}

    class Beli(BaseHTTPRequestHandler):
        def answer(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def login(self):
            return state['sessions'].get(self.headers.get('Authorization', '')[len('Bearer '):])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            if self.path == '/api/token/':
                access = secrets.token_urlsafe(16)
                state['sessions'][access] = body.get('email')
                return self.answer({'access': access, 'refresh': secrets.token_urlsafe(16)})
            if self.login() is None:
                return self.send_error(401)
            if self.path == '/api/add-bookmark/':
                state['saved'].append((self.login(), body['business_id']))
                return self.answer({})
            if self.path == '/api/businesses-res-availability/':
                return self.answer({'results': []})
            self.send_error(404)

        def do_GET(self):
            login = self.login()
            if login is None:
                return self.send_error(401)
            if self.path.startswith('/api/user/logged-in/'):
                return self.answer({'uuid': 'synthetic-' + login})
            if self.path.startswith('/api/get-bookmark/'):
                return self.answer({'Restaurants': [{'business': BISTRO} for who, _ in state['saved'] if who == login]})
            if self.path.startswith('/api/get-ranking/'):
                return self.answer({'results': []})
            if self.path.startswith('/api/trending/'):
                return self.answer({'results': [{'business': BISTRO}]})
            if self.path.startswith('/api/search-app/'):
                return self.answer({'predictions': [{'business': BISTRO['id'], 'structured_formatting':
                                    {'main_text': BISTRO['name'], 'secondary_text': 'New York'}}]})
            if self.path.startswith('/api/business/'):
                return self.answer([BISTRO])
            self.send_error(404)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(FAKE_BELI, Beli), state


# The serving process routes Resy API calls here too; nothing reaches Resy.
FAKE_RESY = ('127.0.0.1', 8767)
RESY_VENUE = {'id': {'resy': 7001}, 'name': 'Synthetic Trattoria', 'type': 'Italian',
              'location': {'neighborhood': 'West Village', 'locality': 'New York'}}
RESY_POLICY = ['Cancel at least 24 hours ahead to avoid the fee.']


def fake_resy():
    """Minimal synthetic Resy API in the shapes resy_client.py reads. Records every booking and cancellation.

    Set state['answer_lost'] to record the next booking and then answer 504, as when
    Resy books the table but the response never arrives.
    """
    state = {'sessions': {}, 'cards': {}, 'reservations': {}, 'sends': [], 'answer_lost': False, 'ids': 70000}
    cut_off = '2099-01-01T00:00:00+00:00'

    def slots(day):
        taken = {r['slot'] for rows in state['reservations'].values() for r in rows}
        offered = [('19:00', {'deposit_fee': 25.0, 'cancellation_fee': 50.0}), ('21:00', {})]
        return [{'config': {'token': f'rgs://resy/7001/1/2/{day}/{day}/{clock}:00/2/Dining Room',
                            'type': 'Dining Room'},
                 'date': {'start': f'{day} {clock}:00', 'end': f'{day} 23:00:00'}, 'payment': payment}
                for clock, payment in offered
                if f'rgs://resy/7001/1/2/{day}/{day}/{clock}:00/2/Dining Room' not in taken]

    def next_id():
        state['ids'] += 1
        return state['ids']

    class Resy(BaseHTTPRequestHandler):
        def answer(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def login(self):
            return state['sessions'].get(self.headers.get('x-resy-auth-token', ''))

        def query(self):
            return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

        def do_POST(self):
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get('Content-Length') or 0))
                                                 .decode()).items()}
            path = urlsplit(self.path).path
            if path == '/3/auth/password':
                token = secrets.token_urlsafe(16)
                state['sessions'][token] = form['email']
                state['cards'].setdefault(form['email'], [{'id': next_id(), 'brand': 'visa', 'last_four': '4242',
                                                           'is_default': True}])
                return self.answer({'token': token})
            login = self.login()
            if login is None:
                return self.send_error(401)
            if path == '/3/book':
                token = form['book_token'].removeprefix('bt:')
                parts = token.split('/')
                assert json.loads(form['struct_payment_method'])['id'] in {c['id'] for c in state['cards'][login]}
                state['sends'].append(('book', login))
                reservation = {'reservation_id': next_id(), 'resy_token': f'rr://{uuid4().hex}', 'day': parts[6],
                               'time_slot': parts[8], 'num_seats': int(parts[9]), 'venue': {'id': 7001},
                               'slot': token, 'status': {'finished': 0, 'no_show': 0},
                               'cancellation': {'allowed': True, 'fee': {'amount': 50.0, 'date_cut_off': cut_off}},
                               'cancellation_policy': RESY_POLICY}
                state['reservations'].setdefault(login, []).append(reservation)
                if state['answer_lost']:
                    state['answer_lost'] = False
                    return self.send_error(504)
                return self.answer({'resy_token': reservation['resy_token'],
                                    'reservation_id': reservation['reservation_id']})
            if path == '/3/cancel':
                rows = state['reservations'].get(login, [])
                assert any(r['resy_token'] == form['resy_token'] for r in rows), "never another login's reservation"
                state['sends'].append(('cancel', login))
                rows[:] = [r for r in rows if r['resy_token'] != form['resy_token']]
                return self.answer({})
            self.send_error(404)

        def do_GET(self):
            login, path, query = self.login(), urlsplit(self.path).path, self.query()
            if path == '/4/find':
                found = query.get('venue_id') == '7001' or 'trattoria' in query.get('query', '').lower()
                return self.answer({'results': {'venues': [{'venue': RESY_VENUE, 'slots': slots(query['day'])}]
                                                if found else []}})
            if login is None:
                return self.send_error(401)
            if path == '/2/user':
                return self.answer({'first_name': 'Synthetic', 'em_address': login,
                                    'payment_methods': state['cards'][login]})
            if path == '/3/venue':
                return self.answer({'venue': RESY_VENUE})
            if path == '/3/details':
                slot = next(s for s in slots(query['day']) if s['config']['token'] == query['config_id'])
                fee = slot['payment'].get('cancellation_fee')
                return self.answer({
                    'book_token': {'value': 'bt:' + query['config_id']}, 'venue': {'name': RESY_VENUE['name']},
                    'payment': {'config': {'type': 'deposit' if fee else 'free'},
                                'amounts': {'total': slot['payment'].get('deposit_fee', 0.0)}},
                    'cancellation': {'fee': {'amount': fee, 'date_cut_off': cut_off},
                                     'display': {'policy': RESY_POLICY}} if fee else {}})
            if path == '/3/user/reservations':
                return self.answer({'reservations': state['reservations'].get(login, []),
                                    'venues': {'7001': {'name': RESY_VENUE['name']}}})
            self.send_error(404)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(FAKE_RESY, Resy), state


# Partiful calls (API functions, sign-in and token refresh) come here too; nothing reaches Partiful or Google.
FAKE_PARTIFUL = ('127.0.0.1', 8768)


def fake_partiful():
    """Minimal synthetic Partiful API in the shapes partiful_client.py reads. Records every read.

    Each token refresh rotates the refresh token and retires the old one, so a
    session only keeps working if every rotation was stored.
    """
    state = {'uids': {}, 'refresh': {}, 'ids': {}, 'events': {}, 'reads': []}

    def session(uid):
        id_token = secrets.token_urlsafe(16)
        refresh = secrets.token_urlsafe(16)
        state['ids'][id_token], state['refresh'][refresh] = uid, uid
        return id_token, refresh

    class Partiful(BaseHTTPRequestHandler):
        def answer(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            path = urlsplit(self.path).path
            if path == '/securetoken':
                uid = state['refresh'].pop(parse_qs(raw.decode()).get('refresh_token', [''])[0], None)
                if uid is None:
                    return self.send_error(400)
                id_token, refresh = session(uid)
                return self.answer({'id_token': id_token, 'refresh_token': refresh, 'expires_in': '3600'})
            body = json.loads(raw or b'{}')
            if path == '/identitytoolkit':
                uid = body.get('token', '')[len('custom-'):]
                id_token, refresh = session(uid)
                return self.answer({'idToken': id_token, 'refreshToken': refresh, 'localId': uid})
            params = (body.get('data') or {}).get('params') or {}
            if path == '/sendAuthCodeTrusted':
                return self.answer({'result': {'data': {}}})
            if path == '/getLoginToken':
                if params.get('authCode') != '123456':
                    return self.answer({'result': {'data': {}}})
                uid = state['uids'].setdefault(params['phoneNumber'], 'partiful-e2e-' + uuid4().hex[:12])
                state['events'].setdefault(uid, [
                    {'id': 'host' + uid[-12:], 'title': 'Synthetic rooftop party', 'startDate': '2026-12-05T01:00:00Z',
                     'location': 'Synthetic Loft', 'status': 'PUBLISHED', 'attendedGuestCount': 9,
                     'guests': [{'name': 'Synthetic Guest', 'phoneNumber': '+15555550100'}], 'hosted': True},
                    {'id': 'inv' + uid[-12:], 'title': 'Synthetic potluck', 'startDate': '2026-12-12T00:00:00Z',
                     'status': 'PUBLISHED', 'guest': {'status': 'GOING'}}])
                return self.answer({'result': {'data': {'customToken': 'custom-' + uid}}})
            uid = state['ids'].get(self.headers.get('Authorization', '')[len('Bearer '):])
            if uid is None:
                return self.send_error(401)
            state['reads'].append((uid, path))
            events = state['events'].get(uid, [])
            if path == '/getPublishedEvents':
                return self.answer({'result': {'data': [e for e in events if e.get('hosted')]}})
            if path == '/getMyRsvps':
                return self.answer({'result': {'data': {'events': [e for e in events if not e.get('hosted')]}}})
            if path == '/getEventInfo':
                event = next((e for e in events if e['id'] == params.get('eventId')), None)
                if event is None:  # Partiful shows only events this session may view
                    return self.send_error(404)
                return self.answer({'result': {'data': {'event': event, 'passwordRequired': False}}})
            self.send_error(404)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(FAKE_PARTIFUL, Partiful), state


# ESPN reads, writes and the public scoreboard come here too; nothing reaches ESPN.
FAKE_ESPN = ('127.0.0.1', 8769)


def fake_espn():
    """Synthetic ESPN Fantasy API over the connector tests' League model, one league per SWID cookie.

    Each league records every write (League.sends). Set answer_lost and hidden on a
    league to record the next write, answer 504 and keep it out of reads until reveal().
    """
    from espn.espn_client import EspnWriteUncertain
    from tests.espn_fakes import League

    state = {'leagues': {}}

    class Espn(BaseHTTPRequestHandler):
        def answer(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def league(self):
            cookies = dict(part.strip().split('=', 1) for part in self.headers.get('Cookie', '').split(';')
                           if '=' in part)
            swid = cookies.get('SWID', '')
            if not cookies.get('espn_s2', '').startswith('synthetic-s2-') or not swid:
                return None
            return state['leagues'].setdefault(swid, League(swid, 'e2e'))

        def do_GET(self):
            path, query = urlsplit(self.path).path, parse_qs(urlsplit(self.path).query)
            if path == '/scoreboard':
                return self.answer({'events': []})
            league = self.league()
            if league is None:
                return self.send_error(401)
            if path == '/reads/seasons/2027/players':
                return self.answer([row['player'] for row in league.league_players()])
            if path == '/reads/seasons/2027/segments/0/leagues/999':
                if query.get('view') == ['kona_player_info']:
                    return self.answer({'players': league.league_players()})
                return self.answer(league.payload(query.get('view', [])))
            self.send_error(404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            league = self.league()
            if league is None:
                return self.send_error(401)
            if urlsplit(self.path).path != '/writes/seasons/2027/segments/0/leagues/999/transactions/':
                return self.send_error(404)
            assert body['memberId'] == league.swid, 'a transaction is only ever sent for the cookie owner'
            team, items = body['teamId'], body['items']
            try:
                if body['type'] == 'ROSTER':
                    return self.answer(league.lineup(team, items))
                if body['type'] in ('FREEAGENT', 'WAIVER'):
                    return self.answer(league.roster(team, [{'action': i['type'], 'playerId': i['playerId']}
                                                            for i in items]))
                give = [i['playerId'] for i in items if i['fromTeamId'] == team]
                receive = [i['playerId'] for i in items if i['toTeamId'] == team]
                counterparty = next(i['toTeamId'] for i in items if i['fromTeamId'] == team)
                return self.answer(league.trade(team, counterparty, give, receive))
            except EspnWriteUncertain:
                return self.send_error(504)

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer(FAKE_ESPN, Espn), state


class MemoryTokens:
    tokens = None
    client = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client

    async def set_client_info(self, client_info):
        self.client = client_info


async def exercise(args):
    import httpx
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.shared.auth import OAuthClientMetadata
    from mcp.types import ServerNotification
    from supabase import create_client
    from trips.ledger import new_group, apply_command

    endpoint, database_url = loopback(args.endpoint), loopback(args.supabase_url)
    service = create_client(database_url, os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY'])
    callback = asyncio.get_running_loop().create_future()
    loop = asyncio.get_running_loop()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != '/callback' or not params.get('code') or not params.get('state'):
                self.send_error(400)
                return
            loop.call_soon_threadsafe(lambda: callback.set_result((params['code'][0], params['state'][0]))
                                     if not callback.done() else None)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Connected. Return to the terminal.')

        def log_message(self, *_args):
            pass  # Authorization codes never enter logs.

    server = HTTPServer(('127.0.0.1', 0), Callback)
    callback_url = f'http://127.0.0.1:{server.server_port}/callback'
    # serve_forever runs only for the lifetime of this exercise.
    serving = asyncio.create_task(asyncio.to_thread(server.serve_forever, poll_interval=0.1))
    beli_server, beli_state = fake_beli()
    beli_serving = asyncio.create_task(asyncio.to_thread(beli_server.serve_forever, poll_interval=0.1))
    service_headers = {'apikey': os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY'],
                       'Authorization': 'Bearer ' + os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY']}

    async def onboard_beli(label):
        """The real /beli/onboard path, against the fake Beli API. Returns (ccb_ token, login, password)."""
        login, password = f'beli-e2e-{uuid4().hex}@example.test', secrets.token_urlsafe(16)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(endpoint[:-len('/mcp')] + '/beli/onboard', json={
                'label': label, 'beli_id': login, 'password': password})
        assert response.status_code == 200, f'Beli onboarding: HTTP {response.status_code}'
        return response.json()['token'], login, password

    resy_server, resy_state = fake_resy()
    resy_serving = asyncio.create_task(asyncio.to_thread(resy_server.serve_forever, poll_interval=0.1))

    partiful_server, partiful_state = fake_partiful()
    partiful_serving = asyncio.create_task(asyncio.to_thread(partiful_server.serve_forever, poll_interval=0.1))

    async def onboard_partiful(label):
        """The real /partiful/onboard start + verify path, against the fake. Returns (ccp_ token, synthetic uid)."""
        phone = '+1555' + ''.join(secrets.choice('0123456789') for _ in range(7))
        async with httpx.AsyncClient(timeout=30) as http:
            started = await http.post(endpoint[:-len('/mcp')] + '/partiful/onboard/start', json={'phone': phone})
            assert started.status_code == 200, f'Partiful onboarding start: HTTP {started.status_code}'
            response = await http.post(endpoint[:-len('/mcp')] + '/partiful/onboard/verify',
                                       json={'phone': phone, 'code': '123456', 'label': label})
        assert response.status_code == 200, f'Partiful onboarding: HTTP {response.status_code}'
        return response.json()['token'], partiful_state['uids'][phone]

    espn_server, espn_state = fake_espn()
    espn_serving = asyncio.create_task(asyncio.to_thread(espn_server.serve_forever, poll_interval=0.1))

    async def onboard_espn(label):
        """The real /espn/onboard path, against the fake ESPN API. Returns (cce_ token, synthetic SWID)."""
        swid = '{' + str(uuid4()).upper() + '}'
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(endpoint[:-len('/mcp')] + '/espn/onboard', json={
                'label': label, 'league_id': 999, 'season': 2027, 'enable_automation': False,
                'espn_s2': 'synthetic-s2-' + secrets.token_urlsafe(16), 'swid': swid})
        assert response.status_code == 200, f'ESPN onboarding: HTTP {response.status_code}'
        return response.json()['token'], swid

    def espn_sends():
        return [(swid, kind) for swid, league in espn_state['leagues'].items() for kind in league.sends]

    async def onboard_resy(label):
        """The real /resy/onboard path, against the fake Resy API. Returns (ccr_ token, synthetic email)."""
        email = f'resy-e2e-{uuid4().hex}@example.test'
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(endpoint[:-len('/mcp')] + '/resy/onboard', json={
                'label': label, 'email': email, 'password': secrets.token_urlsafe(16)})
        assert response.status_code == 200, f'Resy onboarding: HTTP {response.status_code}'
        return response.json()['token'], email

    # Guard every browser-style hop before sending any request (including Location
    # and consent response URLs). Never follow redirects to a hosted service.
    def local_hop(url):
        parsed = urlsplit(url)
        loopback(parsed._replace(query='', fragment='').geturl())
        return url

    class HiddenInputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input' and attrs.get('type') == 'hidden' and attrs.get('name'):
                self.values[attrs['name']] = attrs.get('value', '')

    user_token = None
    async def redirect(url):
        nonlocal user_token
        local_hop(url)
        if args.interactive:
            print('Approve the local connection in the opened browser using a synthetic sandbox account.')
            webbrowser.open(url)
            return
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as browser:
            if user_token is None:
                email = f'commons-e2e-{uuid4().hex}@example.test'
                password = secrets.token_urlsafe(32)
                headers = {'apikey': os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY'],
                           'Authorization': 'Bearer ' + os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY']}
                created = await browser.post(database_url + '/auth/v1/admin/users', headers=headers,
                    json={'email': email, 'password': password, 'email_confirm': True})
                assert created.status_code == 200, f'Create synthetic user: HTTP {created.status_code}'
                signed = await browser.post(database_url + '/auth/v1/token?grant_type=password',
                    headers={'apikey': headers['apikey']}, json={'email': email, 'password': password})
                assert signed.status_code == 200, f'Password sign-in: HTTP {signed.status_code}'
                user_token = signed.json()['access_token']
                print('PASS synthetic local email/password sign-in')
            for _ in range(15):
                local_hop(url)
                parsed = urlsplit(url)
                if parsed.path == '/oauth/consent':
                    authorization_id = parse_qs(parsed.query)['authorization_id'][0]
                    # Same API and user session as frontend/src/auth/OAuthConsent.jsx.
                    headers = {'apikey': os.environ['LOCAL_SUPABASE_SERVICE_ROLE_KEY'],
                               'Authorization': 'Bearer ' + user_token, 'Origin': 'http://localhost:8080'}
                    assert re.fullmatch(r'[A-Za-z0-9_-]{1,128}', authorization_id), 'Invalid authorization ID'
                    authorization = database_url + '/auth/v1/oauth/authorizations/' + authorization_id
                    details = await browser.get(authorization, headers=headers)
                    assert details.status_code == 200, f'Authorization details: HTTP {details.status_code}'
                    data = details.json()
                    if not data.get('redirect_url'):
                        approved = await browser.post(authorization + '/consent', headers=headers,
                                                      json={'action': 'approve'})
                        assert approved.status_code == 200, f'Approve authorization: HTTP {approved.status_code}'
                        data = approved.json()
                    url = data['redirect_url']
                    print('PASS Supabase OAuth authorization consent with user session')
                    continue
                response = await browser.get(url)
                if response.is_redirect:
                    url = urljoin(url, response.headers['location'])
                    continue
                if parsed.path == '/consent':
                    form = HiddenInputs()
                    form.feed(response.text)
                    assert {'txn_id', 'csrf_token'} <= form.values.keys(), 'Missing proxy consent CSRF form'
                    response = await browser.post(url, data={**form.values, 'action': 'approve'})
                    assert response.is_redirect, f'Proxy consent: HTTP {response.status_code}'
                    url = urljoin(url, response.headers['location'])
                    continue
                assert urlsplit(url).path == '/callback' and response.status_code == 200, \
                    f'Unexpected OAuth response: {parsed.path} HTTP {response.status_code}'
                return
            raise AssertionError('Too many local OAuth redirects')

    async def receive():
        return await asyncio.wait_for(callback, timeout=300)

    def provider(scope):
        class RequestedScopes(OAuthClientProvider):
            async def _perform_authorization(self):
                # The pinned SDK replaces client_metadata.scope with advertised
                # scopes during discovery. Select the exercise's least-privilege
                # request after discovery, before its normal DCR/PKCE flow.
                self.context.client_metadata.scope = scope
                return await super()._perform_authorization()

        return RequestedScopes(server_url=endpoint,
            client_metadata=OAuthClientMetadata(client_name='Commons loopback connector exercise',
                redirect_uris=[callback_url], grant_types=['authorization_code', 'refresh_token'],
                response_types=['code'], token_endpoint_auth_method='none', scope=scope),
            storage=MemoryTokens(), redirect_handler=redirect, callback_handler=receive)

    notifications = []

    async def on_message(message):
        if isinstance(message, ServerNotification):
            notifications.append(message.root.method)

    async def listed(session):
        return {tool.name for tool in (await session.list_tools()).tools}

    async def refused(session, name, arguments, fragment, evidence):
        result = await session.call_tool(name, arguments)
        text = ' '.join(getattr(item, 'text', '') for item in result.content)
        assert result.isError and fragment in text, f'{name} not refused as expected: {text}'
        print(f'PASS {evidence}')

    commons = {'whoami', 'list_projects', 'enable_project', 'disable_project'}
    trips = {'get_trip_overview', 'add_expense', 'record_repayment'}
    plans = {'list_floor_plans', 'get_floor_plan', 'describe_floor_plan_schema', 'edit_floor_plan'}
    auth = provider('commons:read commons:edit')
    try:
        async with streamablehttp_client(endpoint, auth=auth) as (read, write, _):
            async with ClientSession(read, write, message_handler=on_message) as session:
                await session.initialize()
                assert auth.context.current_tokens.scope.split() == ['commons:read', 'commons:edit']

                async def call(tool, /, *, evidence=None, **arguments):  # save_restaurant takes `name`
                    result = await session.call_tool(tool, arguments)
                    assert not result.isError, f'{tool} failed: {result.content}'
                    print(f'PASS {evidence or tool}')
                    return result.structuredContent

                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['trips']['enabled'] is False, 'A new user starts without Trips'
                assert projects['trips']['next_step'] == "Call enable_project('trips') to add its 3 tools."
                identity = await call('whoami')
                assert await listed(session) == commons
                print('PASS tools/list for a new user shows only commons tools')
                # Only synthetic data is written. No trips or other user's data are read directly.
                row = new_group(str(uuid4()), identity['id'], f'MCP synthetic {uuid4().hex[:8]}', 'USD', 'Synthetic owner')
                for name in ('Synthetic Alex', 'Synthetic Jamie'):
                    row, _ = apply_command(row, identity['id'], 'add_member', {'name': name, 'revision': row['revision']})
                service.table('trips_groups').insert(row).execute()
                trip_id = row['id']
                print(f'Synthetic trip: {trip_id} (left in loopback sandbox for inspection)')
                projects = {p['id']: p for p in (await call('list_projects', evidence='list_projects after joining a trip'))['projects']}
                assert projects['trips']['enabled'] and projects['trips']['enabled_reason'] == 'default: you already use it'
                assert await listed(session) == commons | trips
                print('PASS default: a user who has trips gets Trips tools without enabling')

                assert await listed(session) == commons | trips
                enabled = await call('enable_project', project_id='floor-planner', evidence='enable_project floor-planner')
                assert {t['name'] for t in enabled['tools']} == plans
                assert 'notifications/tools/list_changed' in notifications
                print('PASS notifications/tools/list_changed delivered on the stateless response stream')
                assert await listed(session) == commons | trips | plans
                print('PASS tools/list after enable_project includes Floor Planner')
                await call('list_floor_plans', evidence='enabled project tool callable')
                await call('disable_project', project_id='floor-planner', evidence='disable_project floor-planner')
                assert await listed(session) == commons | trips
                print('PASS tools/list after disable_project hides Floor Planner')
                await refused(session, 'list_floor_plans', {}, "call enable_project('floor-planner')",
                              'disabled project call refused with the fix')

                await call('get_trip_overview', evidence='get_trip_overview list')
                initial = await call('get_trip_overview', trip_id=trip_id, evidence='get_trip_overview details')
                ids = [member['id'] for member in initial['members']]
                expense = dict(trip_id=trip_id, description='Synthetic dinner', total_cents=10001,
                    payers=[{'member_id': ids[0], 'amount_cents': 10001}], member_ids=ids,
                    idempotency_key=f'expense-{uuid4()}')
                preview = await call('add_expense', **expense, evidence='add_expense dry_run')
                assert preview['dry_run'] and sum(preview['per_person_cents'].values()) == 10001
                unchanged = await call('get_trip_overview', trip_id=trip_id)
                assert unchanged['revision'] == initial['revision']
                saved = await call('add_expense', **expense, dry_run=False, evidence='add_expense commit')
                assert await call('add_expense', **expense, dry_run=False, evidence='add_expense idempotent replay') == saved
                repayment = dict(trip_id=trip_id, from_member_id=ids[1], to_member_id=ids[0],
                    amount_cents=100, idempotency_key=f'repayment-{uuid4()}')
                preview = await call('record_repayment', **repayment, evidence='record_repayment dry_run')
                assert preview['dry_run']
                unchanged = await call('get_trip_overview', trip_id=trip_id)
                assert unchanged['revision'] == saved['revision']
                repaid = await call('record_repayment', **repayment, dry_run=False, evidence='record_repayment commit')
                assert await call('record_repayment', **repayment, dry_run=False, evidence='record_repayment idempotent replay') == repaid
                final = await call('get_trip_overview', trip_id=trip_id)
                assert final['revision'] == initial['revision'] + 2
                assert sum(final['balances_cents'].values()) == 0
                print('PASS real OAuth DCR + PKCE and every Trips tool, previews and replay assertions')

                await call('disable_project', project_id='trips', evidence='disable_project trips')
                await refused(session, 'get_trip_overview', {}, "call enable_project('trips')",
                              'disabled Trips call refused although the user has trips')
                await call('enable_project', project_id='trips', evidence='enable_project trips')
                await call('get_trip_overview', evidence='Trips usable again after enable_project')

                # Beli: off for a new user, then enable, link once, and use without a token.
                beli = {'get_restaurant_recs', 'save_restaurant', 'link_beli_account'}
                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['beli']['enabled'] is False and projects['beli']['linked'] is False
                enabled = await call('enable_project', project_id='beli', evidence='enable_project beli')
                assert enabled['linked'] is False and 'cozycommons.dev/account#beli' in enabled['next_step']
                assert 'ccb_ token in chat' in enabled['next_step']
                assert beli <= await listed(session)
                print('PASS list_projects/enable_project show Beli unlinked with the link step')
                await refused(session, 'get_restaurant_recs', {'neighborhood': 'West Village'},
                              'Link your Beli account first', 'unlinked get_restaurant_recs refused with the link step')
                await refused(session, 'save_restaurant', {'name': 'Synthetic Bistro', 'idempotency_key': 'unlinked',
                              'dry_run': False}, 'Link your Beli account first',
                              'unlinked save_restaurant refused with the link step')
                (beli_token, beli_login, beli_password), (other_token, other_login, _) = (
                    await onboard_beli('e2e-mine'), await onboard_beli('e2e-other'))
                print('PASS synthetic Beli onboarding through /beli/onboard (fake loopback Beli API)')
                async with httpx.AsyncClient(timeout=30) as http:
                    other = await http.post(database_url + '/auth/v1/admin/users', headers=service_headers,
                        json={'email': f'commons-e2e-other-{uuid4().hex}@example.test', 'email_confirm': True})
                assert other.status_code == 200, f'Create second synthetic user: HTTP {other.status_code}'
                from ig_logger.accounts import get_account_row_by_token
                other_account = get_account_row_by_token(service, other_token)['id']
                assert service.rpc('beli_link_account', {'p_account_id': other_account,
                                   'p_user_id': other.json()['id']}).execute().data == 'linked'
                await refused(session, 'link_beli_account', {'api_token': other_token}, 'linked to another Commons user',
                              "link_beli_account refused for another user's account")
                await refused(session, 'link_beli_account', {'api_token': 'ccb_' + secrets.token_urlsafe(32)},
                              'No Beli account matches', 'link_beli_account refused for a wrong token')
                # The account page links with the Beli login itself: no ccb_ token reaches the agent.
                page = endpoint[:-len('/mcp')] + '/account/linked-accounts'
                mine = {'Authorization': 'Bearer ' + user_token}
                async with httpx.AsyncClient(timeout=30) as http:
                    taken = await http.post(page + '/beli', headers=mine,
                                            json={'login': other_login, 'password': 'synthetic'})
                    assert taken.status_code == 409, f"Other user's Beli login: HTTP {taken.status_code}"
                    print("PASS account page refuses another user's Beli login")
                    linked = await http.post(page + '/beli', headers=mine,
                                             json={'login': beli_login.upper(), 'password': beli_password})
                    assert linked.status_code == 200 and linked.json()['status'] == 'linked', linked.text
                    assert beli_token not in linked.text and beli_password not in linked.text
                    assert linked.json()['account']['id'] == get_account_row_by_token(service, beli_token)['id']
                    summary = (await http.get(page, headers=mine)).json()['beli']
                assert summary['id'] == linked.json()['account']['id']
                print('PASS account page links the existing Beli account from its login (fake loopback Beli API)')
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_me = await http.get(endpoint[:-len('/mcp')] + '/beli/me',
                                               headers={'Authorization': 'Bearer ' + beli_token})
                assert legacy_me.status_code == 200 and legacy_me.json()['label'] == 'e2e-mine'
                print('PASS linked account keeps its legacy ccb_ token on /beli')
                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['beli']['linked'] is True and 'get_restaurant_recs' in projects['beli']['next_step']
                print('PASS list_projects shows Beli linked with the next step')
                recs = await call('get_restaurant_recs', neighborhood='West Village', day='saturday', time='19:00',
                                  evidence='get_restaurant_recs')
                assert [r['id'] for r in recs['recs']] == [501]
                save = dict(name='Synthetic Bistro', idempotency_key=f'save-{uuid4()}')
                preview = await call('save_restaurant', **save, evidence='save_restaurant dry_run')
                assert preview['dry_run'] and preview['status'] == 'would_bookmark' and not beli_state['saved']
                saved = await call('save_restaurant', **save, dry_run=False, evidence='save_restaurant commit')
                assert saved['status'] == 'bookmarked' and len(beli_state['saved']) == 1
                assert await call('save_restaurant', **save, dry_run=False,
                                  evidence='save_restaurant idempotent replay') == saved
                await refused(session, 'save_restaurant', {**save, 'city': 'Brooklyn', 'dry_run': False},
                              'used with different details', 'save_restaurant key reuse with new details refused')
                assert len(beli_state['saved']) == 1
                print('PASS every Beli tool over real OAuth: link, recs, preview, commit, replay; one Beli write')

                # Resy: off for a new user, then enable, link once, preview with fees, book and cancel.
                resy = {'find_resy_tables', 'list_resy_reservations', 'book_resy_table', 'cancel_resy_reservation',
                        'link_resy_account'}
                when = (date.today() + timedelta(days=7)).isoformat()
                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['resy']['enabled'] is False and projects['resy']['linked'] is False
                enabled = await call('enable_project', project_id='resy', evidence='enable_project resy')
                assert enabled['linked'] is False and 'link_resy_account' in enabled['next_step']
                assert resy <= await listed(session)
                print('PASS list_projects/enable_project show Resy unlinked with the link step')
                await refused(session, 'find_resy_tables', {'date': when, 'venue_id': 7001},
                              'Link your Resy account first', 'unlinked find_resy_tables refused with the link step')
                await refused(session, 'book_resy_table', {'venue_id': 7001, 'date': when, 'desired_time': '19:00',
                              'idempotency_key': 'unlinked', 'terms_id': '0' * 16, 'dry_run': False},
                              'Link your Resy account first', 'unlinked book_resy_table refused with the link step')
                resy_token, mine_email = await onboard_resy('e2e-mine')
                other_resy, other_email = await onboard_resy('e2e-other')
                print('PASS synthetic Resy onboarding through /resy/onboard (fake loopback Resy API)')
                from resy.accounts import get_account_row_by_token as resy_account_row
                assert service.rpc('resy_link_account', {'p_account_id': resy_account_row(service, other_resy)['id'],
                                   'p_user_id': other.json()['id']}).execute().data == 'linked'
                await refused(session, 'link_resy_account', {'api_token': other_resy}, 'linked to another Commons user',
                              "link_resy_account refused for another user's account")
                await refused(session, 'link_resy_account', {'api_token': 'ccr_' + secrets.token_urlsafe(32)},
                              'No Resy account matches', 'link_resy_account refused for a wrong token')
                linked = await call('link_resy_account', api_token=resy_token, evidence='link_resy_account')
                assert linked['status'] == 'linked' and resy_token not in json.dumps(linked)
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_me = await http.get(endpoint[:-len('/mcp')] + '/resy/me',
                                               headers={'Authorization': 'Bearer ' + resy_token})
                assert legacy_me.status_code == 200 and legacy_me.json()['label'] == 'e2e-mine'
                print('PASS linked account keeps its legacy ccr_ token on /resy')
                tables = await call('find_resy_tables', date=when, venue_id=7001, evidence='find_resy_tables')
                first_slot = tables['venues'][0]['slots'][0]
                assert first_slot['time'] == '19:00' and first_slot['cancellation_fee_cents'] == 5000
                book = {'venue_id': 7001, 'date': when, 'desired_time': '19:00', 'idempotency_key': f'book-{uuid4()}'}
                preview = await call('book_resy_table', **book, evidence='book_resy_table dry_run')
                for text in ('Deposit: USD 25.00 charged to Visa ....4242', 'Cancellation fee: USD 50.00',
                             'Cancel at least 24 hours ahead'):
                    assert text in preview['summary'], preview['summary']
                assert preview['terms']['deposit_cents'] == 2500 and not resy_state['sends']
                print('PASS booking preview shows deposit, cancellation fee, policy and masked card; nothing sent')
                await refused(session, 'book_resy_table', {**book, 'dry_run': False}, 'Preview first',
                              'book_resy_table commit without the previewed terms_id refused')
                commit = {**book, 'terms_id': preview['terms_id'], 'dry_run': False}
                resy_state['answer_lost'] = True
                await refused(session, 'book_resy_table', commit, 'may have gone through',
                              'book_resy_table unconfirmed POST keeps its key and asks for a same-key retry')
                booked = await call('book_resy_table', **commit,
                                    evidence='book_resy_table same-key retry settles from Resy reservations')
                assert booked['status'] == 'booked' and booked['confirmed_from'] == 'your Resy reservations'
                assert resy_state['sends'] == [('book', mine_email)], 'exactly one booking request reached the fake Resy'
                assert await call('book_resy_table', **commit, evidence='book_resy_table idempotent replay') == booked
                await refused(session, 'book_resy_table', {**commit, 'desired_time': '21:00'}, 'already used for',
                              'book_resy_table key reuse with new details refused')
                assert len(resy_state['reservations'][mine_email]) == 1
                print('PASS uncertain booking POST settled once; no duplicate reservation')
                listed_reservations = await call('list_resy_reservations', evidence='list_resy_reservations')
                assert [r['reservation_id'] for r in listed_reservations['reservations']] == [booked['reservation_id']]
                cancel = {'reservation_id': booked['reservation_id'], 'idempotency_key': f'cancel-{uuid4()}'}
                cancel_preview = await call('cancel_resy_reservation', **cancel, evidence='cancel_resy_reservation dry_run')
                assert 'Cancellation fee: USD 50.00' in cancel_preview['summary']
                assert cancel_preview['terms']['fee_applies'] is False and len(resy_state['sends']) == 1
                cancelled = await call('cancel_resy_reservation', **cancel, terms_id=cancel_preview['terms_id'],
                                       dry_run=False, evidence='cancel_resy_reservation commit')
                assert cancelled['status'] == 'cancelled' and not resy_state['reservations'][mine_email]
                assert await call('cancel_resy_reservation', **cancel, terms_id=cancel_preview['terms_id'], dry_run=False,
                                  evidence='cancel_resy_reservation idempotent replay') == cancelled
                other_booking = {'reservation_id': 1, 'resy_token': 'rr://theirs', 'day': when, 'time_slot': '21:00:00',
                                 'num_seats': 2, 'venue': {'id': 7001}, 'slot': 'theirs',
                                 'cancellation': {'allowed': True}, 'status': {}}
                resy_state['reservations'][other_email] = [other_booking]
                await refused(session, 'cancel_resy_reservation', {'reservation_id': 1, 'idempotency_key': f'x-{uuid4()}',
                              'terms_id': '0' * 16, 'dry_run': False}, 'No reservation 1 in your Resy account',
                              "cancel_resy_reservation refused for another user's reservation")
                assert resy_state['sends'] == [('book', mine_email), ('cancel', mine_email)]
                assert resy_state['reservations'][other_email] == [other_booking]
                print('PASS every Resy tool over real OAuth: link, find, list, preview, book, cancel, replay; '
                      'one booking and one cancellation sent')

                # Partiful: read-only. Off for a new user, then enable, link once, list and read events.
                partiful = {'get_partiful_events', 'link_partiful_account'}
                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['partiful']['enabled'] is False and projects['partiful']['linked'] is False
                enabled = await call('enable_project', project_id='partiful', evidence='enable_project partiful')
                assert enabled['linked'] is False and 'link_partiful_account' in enabled['next_step']
                assert partiful <= await listed(session)
                print('PASS list_projects/enable_project show Partiful unlinked with the link step')
                await refused(session, 'get_partiful_events', {}, 'Link your Partiful account first',
                              'unlinked get_partiful_events refused with the link step')
                partiful_token, mine_uid = await onboard_partiful('e2e-mine')
                other_partiful, other_uid = await onboard_partiful('e2e-other')
                print('PASS synthetic Partiful onboarding through /partiful/onboard (fake loopback Partiful API)')
                onboarded_reads = len(partiful_state['reads'])  # onboarding probes each new session once
                from partiful.accounts import get_account_row_by_token as partiful_account_row
                mine_row = partiful_account_row(service, partiful_token)['id']
                assert service.rpc('partiful_link_account', {
                    'p_account_id': partiful_account_row(service, other_partiful)['id'],
                    'p_user_id': other.json()['id']}).execute().data == 'linked'
                await refused(session, 'link_partiful_account', {'api_token': other_partiful},
                              'linked to another Commons user', "link_partiful_account refused for another user's account")
                await refused(session, 'link_partiful_account', {'api_token': 'ccp_' + secrets.token_urlsafe(32)},
                              'No Partiful account matches', 'link_partiful_account refused for a wrong token')
                stored = service.table('partiful_accounts').select('refresh_token_enc,uid_enc,token_hash') \
                    .eq('id', mine_row).single().execute().data
                linked = await call('link_partiful_account', api_token=partiful_token, evidence='link_partiful_account')
                assert linked['status'] == 'linked' and partiful_token not in json.dumps(linked)
                assert service.table('partiful_accounts').select('refresh_token_enc,uid_enc,token_hash') \
                    .eq('id', mine_row).single().execute().data == stored
                print('PASS linking changes only the owner; the stored Partiful session is untouched')
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_me = await http.get(endpoint[:-len('/mcp')] + '/partiful/me',
                                               headers={'Authorization': 'Bearer ' + partiful_token})
                assert legacy_me.status_code == 200 and legacy_me.json()['label'] == 'e2e-mine'
                print('PASS linked account keeps its legacy ccp_ token on /partiful')
                events = await call('get_partiful_events', evidence='get_partiful_events list')
                assert [(e['title'], e['scopes']) for e in events['events']] == [
                    ('Synthetic rooftop party', ['hosted']), ('Synthetic potluck', ['invited', 'rsvp'])]
                assert 'Synthetic Guest' not in json.dumps(events) and '+15555550100' not in json.dumps(events)
                hosted = await call('get_partiful_events', scope='hosted', evidence='get_partiful_events scope=hosted')
                assert [e['title'] for e in hosted['events']] == ['Synthetic rooftop party']
                detail = await call('get_partiful_events', event_id='inv' + mine_uid[-12:],
                                    evidence='get_partiful_events details')
                assert detail['event']['title'] == 'Synthetic potluck' and detail['event']['rsvp_status'] is None
                await refused(session, 'get_partiful_events', {'event_id': 'host' + other_uid[-12:]}, 'Event not found',
                              "get_partiful_events refused for another user's private event")
                assert {uid for uid, _ in partiful_state['reads'][onboarded_reads:]} == {mine_uid}
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_events = await http.get(endpoint[:-len('/mcp')] + '/partiful/events',
                                                   headers={'Authorization': 'Bearer ' + partiful_token})
                assert legacy_events.status_code == 200, \
                    f'/partiful/events: HTTP {legacy_events.status_code} {legacy_events.text[:300]}'
                assert legacy_events.json()['count'] == 2
                print('PASS legacy /partiful/events still works after connector reads rotated the refresh token')
                print('PASS every Partiful tool over real OAuth: link, list, details; only the caller\'s session read')

                # ESPN: off for a new user, then enable, link once, read, and propose -> approve each kind.
                espn = {'get_fantasy_league', 'get_fantasy_trends', 'get_fantasy_activity', 'propose_fantasy_change',
                        'approve_fantasy_change', 'link_espn_account'}
                projects = {p['id']: p for p in (await call('list_projects'))['projects']}
                assert projects['espn']['enabled'] is False and projects['espn']['linked'] is False
                enabled = await call('enable_project', project_id='espn', evidence='enable_project espn')
                assert enabled['linked'] is False and 'link_espn_account' in enabled['next_step']
                assert espn <= await listed(session)
                print('PASS list_projects/enable_project show ESPN unlinked with the link step')
                await refused(session, 'get_fantasy_league', {}, 'Link your ESPN account first',
                              'unlinked get_fantasy_league refused with the link step')
                espn_token, mine_swid = await onboard_espn('e2e-mine')
                other_espn, other_swid = await onboard_espn('e2e-other')
                print('PASS synthetic ESPN onboarding through /espn/onboard (fake loopback ESPN API)')
                from espn.accounts import get_account_row_by_token as espn_account_row
                mine_espn = espn_account_row(service, espn_token)['id']
                other_espn_id = espn_account_row(service, other_espn)['id']
                assert service.rpc('espn_link_account', {'p_account_id': other_espn_id,
                                   'p_user_id': other.json()['id']}).execute().data == 'linked'
                await refused(session, 'link_espn_account', {'api_token': other_espn}, 'linked to another Commons user',
                              "link_espn_account refused for another user's account")
                await refused(session, 'link_espn_account', {'api_token': 'cce_' + secrets.token_urlsafe(32)},
                              'No ESPN account matches', 'link_espn_account refused for a wrong token')
                stored_espn = service.table('espn_accounts').select('espn_s2_enc,swid_enc,token_hash') \
                    .eq('id', mine_espn).single().execute().data
                linked = await call('link_espn_account', api_token=espn_token, evidence='link_espn_account')
                assert linked['status'] == 'linked' and espn_token not in json.dumps(linked)
                assert service.table('espn_accounts').select('espn_s2_enc,swid_enc,token_hash') \
                    .eq('id', mine_espn).single().execute().data == stored_espn
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_me = await http.get(endpoint[:-len('/mcp')] + '/espn/me',
                                               headers={'Authorization': 'Bearer ' + espn_token})
                assert legacy_me.status_code == 200 and legacy_me.json()['label'] == 'e2e-mine'
                print('PASS linking changes only the owner; the legacy cce_ token still works on /espn')
                overview = await call('get_fantasy_league', evidence='get_fantasy_league view=league')
                assert overview['your_team_id'] == 7 and len(overview['teams']) == 2
                team = await call('get_fantasy_league', view='team', evidence='get_fantasy_league view=team (yours)')
                assert team['team']['team_id'] == 7
                await call('get_fantasy_league', view='standings', evidence='get_fantasy_league view=standings')
                await call('get_fantasy_trends', kind='teams', evidence='get_fantasy_trends kind=teams')
                await call('get_fantasy_trends', kind='players', evidence='get_fantasy_trends kind=players')
                assert not espn_sends()
                plan = await call('propose_fantasy_change', kind='lineup', evidence='propose_fantasy_change lineup')
                assert 'Synthetic Player 101 bench -> UTIL' in plan['summary'] and not espn_sends()
                lineup_approval = dict(kind='lineup', proposal_id=plan['proposal_id'], idempotency_key=f'lineup-{uuid4()}')
                preview = await call('approve_fantasy_change', **lineup_approval,
                                     evidence='approve_fantasy_change lineup dry_run')
                assert preview['status'] == 'would_approve' and not espn_sends()
                lineup_done = await call('approve_fantasy_change', **lineup_approval, dry_run=False,
                                         evidence='approve_fantasy_change lineup commit')
                assert lineup_done['status'] == 'ok' and espn_sends() == [(mine_swid, 'lineup')]
                assert await call('approve_fantasy_change', **lineup_approval, dry_run=False,
                                  evidence='approve_fantasy_change lineup idempotent replay') == lineup_done
                edit = await call('propose_fantasy_change', kind='roster_edit', add_player_id=9001, drop_player_id=105,
                                  evidence='propose_fantasy_change roster_edit')
                edit_approval = dict(kind='roster_edit', proposal_id=edit['proposal_id'],
                                     idempotency_key=f'edit-{uuid4()}')
                assert (await call('approve_fantasy_change', **edit_approval,
                                   evidence='approve_fantasy_change roster_edit dry_run'))['status'] == 'would_approve'
                espn_state['leagues'][mine_swid].answer_lost = espn_state['leagues'][mine_swid].hidden = True
                await refused(session, 'approve_fantasy_change', {**edit_approval, 'dry_run': False}, 'not confirmed',
                              'approve_fantasy_change lost ESPN answer keeps its key and asks for a same-key retry')
                await refused(session, 'approve_fantasy_change', {**edit_approval, 'dry_run': False}, 'not confirmed',
                              'approve_fantasy_change same-key retry before ESPN shows it: reads only, still open')
                espn_state['leagues'][mine_swid].reveal()
                settled = await call('approve_fantasy_change', **edit_approval, dry_run=False,
                                     evidence='approve_fantasy_change same-key retry settles from ESPN')
                assert settled['status'] == 'executed' and settled['confirmed_from'] == 'ESPN'
                assert await call('approve_fantasy_change', **edit_approval, dry_run=False,
                                  evidence='approve_fantasy_change roster_edit idempotent replay') == settled
                await refused(session, 'approve_fantasy_change', {**edit_approval, 'proposal_id': plan['proposal_id'],
                              'kind': 'lineup', 'dry_run': False}, 'already used for',
                              'approve_fantasy_change key reuse for another proposal refused')
                assert espn_sends() == [(mine_swid, 'lineup'), (mine_swid, 'roster_edit')]
                print('PASS lost roster-edit answer settled once by reading ESPN; no second submission')
                offer = await call('propose_fantasy_change', kind='trade', counterparty_team_id=8,
                                   give_player_ids=[106], receive_player_ids=[201],
                                   evidence='propose_fantasy_change trade')
                offered = await call('approve_fantasy_change', kind='trade', proposal_id=offer['proposal_id'],
                                     idempotency_key=f'trade-{uuid4()}', dry_run=False,
                                     evidence='approve_fantasy_change trade commit')
                assert offered['status'] == 'offered'
                activity = await call('get_fantasy_activity', kind='roster_edits', evidence='get_fantasy_activity')
                assert [e['status'] for e in activity['edits']] == ['executed']
                one = await call('get_fantasy_activity', kind='trades', proposal_id=offer['proposal_id'],
                                 evidence='get_fantasy_activity one trade')
                assert one['status'] == 'offered'
                theirs = service.table('espn_roster_edits').insert({
                    'account_id': other_espn_id, 'league_id': 999, 'season': 2027, 'team_id': 7,
                    'drop_player_id': 105, 'preview': 'Synthetic other edit', 'status': 'pending',
                    'expires_at': '2099-01-01T00:00:00+00:00'}).execute().data[0]['id']
                await refused(session, 'get_fantasy_activity', {'kind': 'roster_edits', 'proposal_id': theirs},
                              'in your ESPN account', "get_fantasy_activity refused for another user's edit")
                await refused(session, 'approve_fantasy_change', {'kind': 'roster_edit', 'proposal_id': theirs,
                              'idempotency_key': f'x-{uuid4()}', 'dry_run': False}, 'in your ESPN account',
                              "approve_fantasy_change refused for another user's edit")
                async with httpx.AsyncClient(timeout=30) as http:
                    legacy_edits = await http.get(endpoint[:-len('/mcp')] + '/espn/roster/edits',
                                                  headers={'Authorization': 'Bearer ' + espn_token})
                assert legacy_edits.status_code == 200 and legacy_edits.json()['count'] == 1
                print('PASS legacy /espn/roster/edits sees the connector edit through the same gate')
                assert espn_sends() == [(mine_swid, 'lineup'), (mine_swid, 'roster_edit'), (mine_swid, 'trade')]
                assert other_swid not in {swid for swid, _kind in espn_sends()}
                print('PASS every ESPN tool over real OAuth: link, league, trends, activity, propose and approve; '
                      'one lineup, one roster edit and one trade sent')
                access_token = auth.context.current_tokens.access_token
        callback = loop.create_future()
        readonly = provider('commons:read')
        async with streamablehttp_client(endpoint, auth=readonly) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert readonly.context.current_tokens.scope.split() == ['commons:read']
                await refused(session, 'add_expense', {**expense, 'dry_run': False, 'idempotency_key': f'denied-{uuid4()}'},
                              'commons:edit', 'read-only token denied on add_expense')
                await refused(session, 'record_repayment', {**repayment, 'dry_run': False, 'idempotency_key': f'denied-{uuid4()}'},
                              'commons:edit', 'read-only token denied on record_repayment')
                assert not (await session.call_tool('get_trip_overview', {'trip_id': trip_id})).isError
                final_row = service.table('trips_groups').select('revision').eq('id', trip_id).single().execute().data
                assert final_row['revision'] == final['revision']
                print('PASS read-only token reads Trips; writes refused; ledger unchanged')
                await refused(session, 'save_restaurant', {**save, 'idempotency_key': f'denied-{uuid4()}', 'dry_run': False},
                              'commons:edit', 'read-only token denied on save_restaurant')
                assert not (await session.call_tool('get_restaurant_recs', {'neighborhood': 'West Village'})).isError
                assert len(beli_state['saved']) == 1
                print('PASS read-only token reads Beli recs; saves refused; no Beli write')
                await refused(session, 'book_resy_table', {**book, 'idempotency_key': f'denied-{uuid4()}',
                              'desired_time': '21:00', 'terms_id': '0' * 16, 'dry_run': False},
                              'commons:edit', 'read-only token denied on book_resy_table')
                await refused(session, 'cancel_resy_reservation', {'reservation_id': 1, 'idempotency_key': 'denied',
                              'terms_id': '0' * 16, 'dry_run': False}, 'commons:edit',
                              'read-only token denied on cancel_resy_reservation')
                assert not (await session.call_tool('find_resy_tables', {'date': when, 'venue_id': 7001})).isError
                assert len(resy_state['sends']) == 2
                print('PASS read-only token finds Resy tables; bookings and cancellations refused; nothing sent')
                await refused(session, 'link_partiful_account', {'api_token': partiful_token}, 'commons:edit',
                              'read-only token denied on link_partiful_account')
                readonly_events = await session.call_tool('get_partiful_events', {})
                assert not readonly_events.isError and readonly_events.structuredContent['count'] == 2
                print('PASS read-only token reads Partiful events; linking refused')
                await refused(session, 'propose_fantasy_change', {'kind': 'lineup'}, 'commons:edit',
                              'read-only token denied on propose_fantasy_change')
                await refused(session, 'approve_fantasy_change', {**edit_approval, 'dry_run': False}, 'commons:edit',
                              'read-only token denied on approve_fantasy_change')
                assert not (await session.call_tool('get_fantasy_league', {})).isError
                assert len(espn_sends()) == 3
                print('PASS read-only token reads the ESPN league; proposals and approvals refused; nothing sent')

        # A token minted exactly as the M1 deployment did: same signing key and
        # upstream mapping (jti), pre-commons scopes. It keeps its old reach.
        from cc_mcp.registry import PROVIDERS
        from cc_mcp.server import create_agent_app
        import jwt as pyjwt
        issuer = create_agent_app(service, providers=PROVIDERS).state.cc_mcp_oauth.jwt_issuer
        claims = pyjwt.decode(access_token, options={'verify_signature': False})
        legacy = issuer.issue_access_token(claims['client_id'], ['trips:read', 'trips:edit'], claims['jti'], 600)
        async with streamablehttp_client(endpoint, headers={'Authorization': f'Bearer {legacy}'}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                overview = await session.call_tool('get_trip_overview', {'trip_id': trip_id})
                assert not overview.isError and overview.structuredContent['revision'] == final['revision']
                preview = await session.call_tool('add_expense', {**expense, 'idempotency_key': f'legacy-{uuid4()}'})
                assert not preview.isError and preview.structuredContent['dry_run']
                print('PASS pre-commons trips:* token still reads and previews Trips until it expires')
                assert not (await session.call_tool('enable_project', {'project_id': 'floor-planner'})).isError
                await refused(session, 'list_floor_plans', {}, 'Reconnect your agent once',
                              'pre-commons token refused outside its old project with a reconnect step')
                assert not (await session.call_tool('disable_project', {'project_id': 'floor-planner'})).isError

        # Disconnect from the account page: the same API and session the /account page uses.
        origin = endpoint[:-len('/mcp')]
        main_tokens, readonly_tokens = auth.context.current_tokens, readonly.context.current_tokens
        mcp_call = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'whoami', 'arguments': {}}}

        def bearer(token):
            return {'Authorization': f'Bearer {token}', 'Accept': 'application/json, text/event-stream'}

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            mine = {'Authorization': 'Bearer ' + user_token}
            listed = await http.get(origin + '/account/connections', headers=mine)
            assert listed.status_code == 200 and listed.headers['cache-control'] == 'private, no-store'
            agents = {tuple(agent['scopes']): agent for agent in listed.json()}
            assert set(agents) == {('commons:read', 'commons:edit'), ('commons:read',)}, listed.json()
            assert {(a['client_name'], a['redirect_host']) for a in agents.values()} == {
                ('Commons loopback connector exercise', '127.0.0.1')}
            assert all(a['approved_at'] and a['last_used_at'] and a['expires_at'] for a in agents.values())
            print('PASS account lists each agent connection with its client name, redirect host and last use')
            target = agents[('commons:read', 'commons:edit')]['id']

            email, password = f'commons-e2e-other-{uuid4().hex}@example.test', secrets.token_urlsafe(32)
            created = await http.post(database_url + '/auth/v1/admin/users', headers=service_headers,
                                      json={'email': email, 'password': password, 'email_confirm': True})
            assert created.status_code == 200, f'Create second synthetic user: HTTP {created.status_code}'
            other = await http.post(database_url + '/auth/v1/token?grant_type=password',
                                    headers={'apikey': service_headers['apikey']}, json={'email': email, 'password': password})
            theirs = {'Authorization': 'Bearer ' + other.json()['access_token']}
            assert (await http.get(origin + '/account/connections', headers=theirs)).json() == []
            assert (await http.delete(f'{origin}/account/connections/{target}', headers=theirs)).status_code == 404
            assert (await http.post(endpoint, headers=bearer(main_tokens.access_token), json=mcp_call)).status_code == 200
            print("PASS another user's disconnect returns 404 and the connection keeps working")

            assert (await http.delete(f'{origin}/account/connections/{target}', headers=mine)).status_code == 204
            assert (await http.post(endpoint, headers=bearer(main_tokens.access_token), json=mcp_call)).status_code == 401
            assert (await http.post(endpoint, headers=bearer(legacy), json=mcp_call)).status_code == 401
            refreshed = await http.post(origin + '/token', data={
                'grant_type': 'refresh_token', 'refresh_token': main_tokens.refresh_token,
                'client_id': auth.context.client_info.client_id})
            assert refreshed.status_code == 400 and refreshed.json()['error'] == 'invalid_grant', refreshed.text
            assert (await http.delete(f'{origin}/account/connections/{target}', headers=mine)).status_code == 204
            remaining = (await http.get(origin + '/account/connections', headers=mine)).json()
            assert [tuple(agent['scopes']) for agent in remaining] == [('commons:read',)]
            still = await http.post(endpoint, headers=bearer(readonly_tokens.access_token), json=mcp_call)
            assert still.status_code == 200 and '"result"' in still.text and '"isError":true' not in still.text, still.text
            print('PASS disconnect from account revokes access and refresh')
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await serving
        await asyncio.to_thread(beli_server.shutdown)
        beli_server.server_close()
        await beli_serving
        await asyncio.to_thread(resy_server.shutdown)
        resy_server.server_close()
        await resy_serving
        await asyncio.to_thread(partiful_server.shutdown)
        partiful_server.server_close()
        await partiful_serving
        await asyncio.to_thread(espn_server.shutdown)
        espn_server.server_close()
        await espn_serving


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true', help='Approve consent in a browser instead of unattended local Auth')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8000/mcp')
    parser.add_argument('--supabase-url', default='http://127.0.0.1:54321')
    asyncio.run(exercise(parser.parse_args()))
