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
from http.server import BaseHTTPRequestHandler, HTTPServer
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
            client_metadata=OAuthClientMetadata(client_name='Commons loopback M1 exercise',
                redirect_uris=[callback_url], grant_types=['authorization_code', 'refresh_token'],
                response_types=['code'], token_endpoint_auth_method='none', scope=scope),
            storage=MemoryTokens(), redirect_handler=redirect, callback_handler=receive)

    auth = provider('trips:read trips:edit')
    try:
        async with streamablehttp_client(endpoint, auth=auth) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, *, evidence=None, **arguments):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, f'{name} failed: {result.content}'
                    print(f'PASS {evidence or name}')
                    return result.structuredContent

                await call('list_projects')
                identity = await call('whoami')
                # Only synthetic data is written. No trips or other user's data are read directly.
                row = new_group(str(uuid4()), identity['id'], f'MCP synthetic {uuid4().hex[:8]}', 'USD', 'Synthetic owner')
                for name in ('Synthetic Alex', 'Synthetic Jamie'):
                    row, _ = apply_command(row, identity['id'], 'add_member', {'name': name, 'revision': row['revision']})
                service.table('trips_groups').insert(row).execute()
                trip_id = row['id']
                print(f'Synthetic trip: {trip_id} (left in loopback sandbox for inspection)')
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
                print('PASS real OAuth DCR + PKCE and all M1 tools, previews and replay assertions')
        callback = loop.create_future()
        readonly = provider('trips:read')
        async with streamablehttp_client(endpoint, auth=readonly) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert readonly.context.current_tokens.scope.split() == ['trips:read']
                denied = await session.call_tool('add_expense', {**expense, 'dry_run': False,
                    'idempotency_key': f'denied-{uuid4()}'})
                assert denied.isError and 'trips:edit' in str(denied.content), denied
                final_row = service.table('trips_groups').select('revision').eq('id', trip_id).single().execute().data
                assert final_row['revision'] == final['revision']
                print('PASS token without trips:edit denied on write; ledger unchanged')
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await serving


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true', help='Approve consent in a browser instead of unattended local Auth')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8000/mcp')
    parser.add_argument('--supabase-url', default='http://127.0.0.1:54321')
    asyncio.run(exercise(parser.parse_args()))
