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
        """The real /beli/onboard path, against the fake Beli API. Returns the ccb_ token."""
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(endpoint[:-len('/mcp')] + '/beli/onboard', json={
                'label': label, 'beli_id': f'beli-e2e-{uuid4().hex}@example.test',
                'password': secrets.token_urlsafe(16)})
        assert response.status_code == 200, f'Beli onboarding: HTTP {response.status_code}'
        return response.json()['token']

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
                assert enabled['linked'] is False and 'link_beli_account' in enabled['next_step']
                assert beli <= await listed(session)
                print('PASS list_projects/enable_project show Beli unlinked with the link step')
                await refused(session, 'get_restaurant_recs', {'neighborhood': 'West Village'},
                              'Link your Beli account first', 'unlinked get_restaurant_recs refused with the link step')
                await refused(session, 'save_restaurant', {'name': 'Synthetic Bistro', 'idempotency_key': 'unlinked',
                              'dry_run': False}, 'Link your Beli account first',
                              'unlinked save_restaurant refused with the link step')
                beli_token, other_token = await onboard_beli('e2e-mine'), await onboard_beli('e2e-other')
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
                linked = await call('link_beli_account', api_token=beli_token, evidence='link_beli_account')
                assert linked['status'] == 'linked' and beli_token not in json.dumps(linked)
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
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await serving
        await asyncio.to_thread(beli_server.shutdown)
        beli_server.server_close()
        await beli_serving


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true', help='Approve consent in a browser instead of unattended local Auth')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8000/mcp')
    parser.add_argument('--supabase-url', default='http://127.0.0.1:54321')
    asyncio.run(exercise(parser.parse_args()))
