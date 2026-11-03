#!/usr/bin/env python3
"""Real DCR + PKCE + Streamable HTTP exercise, exclusively on loopback Supabase.

Run with backend/.venv/bin/python. Requires the configured loopback app and OAuth
client described in docs/mcp/README.md. Approve consent in the opened browser
using a synthetic local account. Tokens stay in memory; never print credentials.
LOCAL_SUPABASE_SERVICE_ROLE_KEY is read only after both URL guards pass.
"""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
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

    async def redirect(url):
        print('Approve the local connection in the opened browser using a synthetic sandbox account.')
        webbrowser.open(url)

    async def receive():
        return await asyncio.wait_for(callback, timeout=300)

    auth = OAuthClientProvider(server_url=endpoint,
        client_metadata=OAuthClientMetadata(client_name='Commons loopback M1 exercise',
            redirect_uris=[callback_url], grant_types=['authorization_code', 'refresh_token'],
            response_types=['code'], token_endpoint_auth_method='none'),
        storage=MemoryTokens(), redirect_handler=redirect, callback_handler=receive)
    try:
        async with streamablehttp_client(endpoint, auth=auth) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, **arguments):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, f'{name} failed: {result.content}'
                    print(f'PASS {name}')
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
                await call('get_trip_overview')
                initial = await call('get_trip_overview', trip_id=trip_id)
                ids = [member['id'] for member in initial['members']]
                expense = dict(trip_id=trip_id, description='Synthetic dinner', total_cents=10001,
                    payers=[{'member_id': ids[0], 'amount_cents': 10001}], member_ids=ids,
                    idempotency_key=f'expense-{uuid4()}')
                preview = await call('add_expense', **expense)
                assert preview['dry_run'] and sum(preview['per_person_cents'].values()) == 10001
                unchanged = await call('get_trip_overview', trip_id=trip_id)
                assert unchanged['revision'] == initial['revision']
                saved = await call('add_expense', **expense, dry_run=False)
                assert await call('add_expense', **expense, dry_run=False) == saved
                repayment = dict(trip_id=trip_id, from_member_id=ids[1], to_member_id=ids[0],
                    amount_cents=100, idempotency_key=f'repayment-{uuid4()}')
                preview = await call('record_repayment', **repayment)
                assert preview['dry_run']
                unchanged = await call('get_trip_overview', trip_id=trip_id)
                assert unchanged['revision'] == saved['revision']
                repaid = await call('record_repayment', **repayment, dry_run=False)
                assert await call('record_repayment', **repayment, dry_run=False) == repaid
                final = await call('get_trip_overview', trip_id=trip_id)
                assert final['revision'] == initial['revision'] + 2
                assert sum(final['balances_cents'].values()) == 0
                print('PASS real OAuth DCR + PKCE and all M1 tools, previews and replay assertions')
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await serving


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='http://127.0.0.1:8000/mcp')
    parser.add_argument('--supabase-url', default='http://127.0.0.1:54321')
    asyncio.run(exercise(parser.parse_args()))
