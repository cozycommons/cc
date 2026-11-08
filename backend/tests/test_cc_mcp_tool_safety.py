"""Every tool on /mcp, enumerated from the live registry, passes the same safety gates.

A new provider or tool fails here until it has a fixture below: valid arguments
for each tool, and either arguments that target another user's resource or a
stated reason the tool has none. Calls go through the full server, so the access
middleware, scope checks and the tool's own ownership checks all run.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import COMMONS, EDIT_SCOPE, LEVEL_SCOPE, READ_SCOPE, build_server
from tests import beli_fakes, espn_fakes, partiful_fakes, resy_fakes
from tests.test_commons_agent_tools import Database, expense_args, repayment_args


@dataclass(frozen=True)
class Fixture:
    args: Callable[[Database], dict]
    foreign: Callable[[Database, pytest.MonkeyPatch], dict] = lambda db, monkeypatch: {}
    foreign_error: str | dict[str, str] = ''
    no_resource: dict = field(default_factory=dict)


def trips_foreign(db, _monkeypatch):
    db.row['member_user_ids'] = [str(uuid4())]
    return {'get_trip_overview': {'trip_id': db.row['id']}, 'add_expense': expense_args(db, dry_run=False),
            'record_repayment': repayment_args(db, dry_run=False)}


PLAN_ID = str(uuid4())


def plans_foreign(_db, monkeypatch):
    document = {'id': PLAN_ID, 'owner_id': str(uuid4()), 'revision': 1, 'scene': {}}
    monkeypatch.setattr('floor_planner.agent_tools.get_document', lambda client, plan_id: document)
    monkeypatch.setattr('floor_planner.agent_tools.document_access', lambda client, document, user: None)
    return {'get_floor_plan': {'plan_id': PLAN_ID},
            'edit_floor_plan': {'plan_id': PLAN_ID, 'expected_revision': 1, 'operations': []}}


def beli_foreign(db, _monkeypatch):
    # Another user's linked account: the caller is unlinked.
    beli_fakes.add_account(db, owner=str(uuid4()))
    return {'get_restaurant_recs': {'neighborhood': 'West Village'},
            'save_restaurant': {'name': 'Synthetic Bistro', 'idempotency_key': 'save-1', 'dry_run': False}}


def resy_foreign(db, _monkeypatch):
    # The caller is linked to their own Resy account; the targets belong to another linked user.
    resy_fakes.add_account(db, owner=db.user.id)
    other, _token = resy_fakes.add_account(db, owner=str(uuid4()))
    theirs = resy_fakes.add_reservation(db, other['email'])
    stale = {'terms_id': '0' * 16, 'dry_run': False}
    return {'book_resy_table': {**RESY_BOOK, 'payment_method_id': db.resy_cards[other['email']][0]['id'], **stale},
            'cancel_resy_reservation': {'reservation_id': theirs['reservation_id'], 'idempotency_key': 'cancel-1',
                                        **stale}}


def partiful_foreign(db, _monkeypatch):
    # The caller is linked to their own Partiful account; the event belongs to another linked user.
    partiful_fakes.add_account(db, owner=db.user.id)
    other, _token = partiful_fakes.add_account(db, owner=str(uuid4()))
    return {'get_partiful_events': {'event_id': db.partiful_events[other['uid']]['hosted'][0]['id']}}


def espn_foreign(db, _monkeypatch):
    # The caller is linked to their own ESPN account; the edit and player belong to another linked user.
    espn_fakes.add_account(db, owner=db.user.id)
    other, _token = espn_fakes.add_account(db, owner=str(uuid4()))
    theirs = espn_fakes.add_edit(db, other)
    return {'get_fantasy_activity': {'kind': 'roster_edits', 'proposal_id': theirs['id']},
            'propose_fantasy_change': {'kind': 'roster_edit', 'drop_player_id': espn_fakes.RIVAL_STAR},
            'approve_fantasy_change': {'kind': 'roster_edit', 'proposal_id': theirs['id'],
                                       'idempotency_key': 'approve-1', 'dry_run': False}}


ESPN_APPROVE = {'kind': 'roster_edit', 'proposal_id': str(uuid4()), 'idempotency_key': 'approve-1'}
ESPN_PROPOSE = {'kind': 'roster_edit', 'add_player_id': espn_fakes.FREE_AGENT, 'drop_player_id': espn_fakes.DROP}

RESY_BOOK = {'venue_id': resy_fakes.VENUE_ID, 'date': resy_fakes.day(), 'desired_time': '19:00',
             'idempotency_key': 'book-1'}

def apps_foreign(db, monkeypatch):
    # The HTTP transport reaches the real manager authorization code; see the
    # fixture below. No app belongs to this caller.
    return {'set_app_member': {'app': 'foreign', 'user': str(uuid4()), 'role': 'viewer'},
            'exec_command': {'app': 'foreign', 'command': 'echo synthetic'},
            'transfer_file': {'app': 'foreign', 'path': '/workspace/file', 'direction': 'download'},
            'app_backups': {'app': 'foreign', 'action': 'list'}}


FIXTURES = {
    'apps': Fixture(
        args=lambda db: {'list_apps': {}, 'create_app': {'name': 'fresh'},
                         'set_app_member': {'app': 'foreign', 'user': str(uuid4()), 'role': 'viewer'},
                         'exec_command': {'app': 'foreign', 'command': 'echo synthetic'},
            'transfer_file': {'app': 'foreign', 'path': '/workspace/file', 'direction': 'download'},
            'app_backups': {'app': 'foreign', 'action': 'list'}},
        foreign=apps_foreign, foreign_error='App or job not found',
        no_resource={'list_apps': 'lists only caller memberships',
                     'create_app': 'allocates new unique slug, subject to creator permission'}),
    COMMONS: Fixture(
        args=lambda db: {'whoami': {}, 'list_projects': {}, 'enable_project': {'project_id': 'trips'},
                         'disable_project': {'project_id': 'trips'}},
        no_resource={name: 'acts only on the signed-in user' for name in
                     ('whoami', 'list_projects', 'enable_project', 'disable_project')}),
    'trips': Fixture(
        args=lambda db: {'get_trip_overview': {'trip_id': db.row['id']}, 'add_expense': expense_args(db),
                         'record_repayment': repayment_args(db)},
        foreign=trips_foreign, foreign_error='not a member'),
    'floor-planner': Fixture(
        args=lambda db: {'list_floor_plans': {}, 'get_floor_plan': {'plan_id': PLAN_ID},
                         'describe_floor_plan_schema': {},
                         'edit_floor_plan': {'plan_id': PLAN_ID, 'expected_revision': 1, 'operations': []}},
        foreign=plans_foreign, foreign_error='Plan not found or you do not have access',
        no_resource={'list_floor_plans': 'lists only plans the user owns or was invited to',
                     'describe_floor_plan_schema': 'static schema'}),
    'beli': Fixture(
        args=lambda db: {'get_restaurant_recs': {'neighborhood': 'West Village'},
                         'save_restaurant': {'name': 'Synthetic Bistro', 'idempotency_key': 'save-1'}},
        foreign=beli_foreign,
        foreign_error={'get_restaurant_recs': 'Link your Beli account first',
                       'save_restaurant': 'Link your Beli account first'}),
    'resy': Fixture(
        args=lambda db: {'find_resy_tables': {'date': resy_fakes.day(), 'venue_id': resy_fakes.VENUE_ID},
                         'list_resy_reservations': {}, 'book_resy_table': RESY_BOOK,
                         'cancel_resy_reservation': {'reservation_id': 1, 'idempotency_key': 'cancel-1'}},
        foreign=resy_foreign,
        foreign_error={'book_resy_table': 'is not on your Resy account',
                       'cancel_resy_reservation': 'No reservation .* in your Resy account'},
        no_resource={'find_resy_tables': 'public venue availability, read with the caller’s own linked login',
                     'list_resy_reservations': 'lists only the caller’s own linked Resy account'}),
    'partiful': Fixture(
        args=lambda db: {'get_partiful_events': {}},
        foreign=partiful_foreign,
        foreign_error={'get_partiful_events': 'Event not found'}),
    'espn': Fixture(
        args=lambda db: {'get_fantasy_league': {}, 'get_fantasy_trends': {'kind': 'teams'},
                         'get_fantasy_activity': {'kind': 'roster_edits'}, 'propose_fantasy_change': ESPN_PROPOSE,
                         'approve_fantasy_change': ESPN_APPROVE},
        foreign=espn_foreign,
        foreign_error={'get_fantasy_activity': 'No roster edit .* in your ESPN account',
                       'propose_fantasy_change': 'is not on your roster',
                       'approve_fantasy_change': 'No roster edit .* in your ESPN account'},
        no_resource={'get_fantasy_league': 'reads only the league of the caller’s own linked cookies',
                     'get_fantasy_trends': 'reads only the league of the caller’s own linked cookies'}),
}

CASES = [pytest.param(provider, tool, level, id=f'{provider.name}.{tool}')
         for provider in PROVIDERS for tool, level in provider.tools.items()]
PROJECTS = [provider for provider in PROVIDERS if provider.name != COMMONS]


@pytest.fixture
def server(monkeypatch, tmp_path):
    db = Database()
    db.user.email_confirmed_at = '2026-01-01T00:00:00Z'
    beli_fakes.install(db, monkeypatch)
    resy_fakes.install(db, monkeypatch)
    partiful_fakes.install(db, monkeypatch)
    espn_fakes.install(db, monkeypatch)
    for provider in PROJECTS:
        db.settings[(db.user.id, provider.name)] = {'user_id': db.user.id, 'project_id': provider.name, 'enabled': True}
    # In-process HTTP to the actual manager: prove authorization across the
    # OAuth bridge, rather than mocking the ownership decision.
    import importlib
    import sys
    import httpx
    from app_runtime.tests.test_api import FakeRuntime
    # Shared backend intentionally has no Docker SDK dependency/socket. Stub
    # only the driver module; use the real manager API and authorization code.
    monkeypatch.setitem(sys.modules, 'app_runtime.docker_runtime', SimpleNamespace(Runtime=FakeRuntime, TRANSFER_LIMIT=16 * 1024 * 1024))
    for key, value in {'APPS_MODE': 'hosted', 'APPS_DOMAIN': 'example.test',
                       'APPS_SUPABASE_URL': 'https://project.supabase.co',
                       'APPS_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test',
                       'APPS_MCP_OAUTH_CLIENT_ID': '20000000-0000-4000-8000-000000000001',
                       'APPS_RUNTIME_IMAGE': 'runtime:test', 'APPS_CREATORS': db.user.id,
                       'APPS_STATE': str(tmp_path), 'APPS_PROXY_CONFIG': str(tmp_path / 'Caddyfile'),
                       'APPS_MANAGER_URL': 'https://apps.example.test'}.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop('app_runtime.api', None)
    manager = importlib.import_module('app_runtime.api')
    monkeypatch.setattr(manager.hosted_auth, 'user', lambda token: db.user.id if token == 'synthetic' else None)
    monkeypatch.setattr(manager.hosted_auth, 'can_create', lambda token, user_id: user_id == db.user.id)
    from app_runtime.core import digest
    manager.store.put({'name': 'foreign', 'status': 'running', 'members': {str(uuid4()): 'owner'},
                       'routes': {}, 'app_token_hash': digest('private')})
    real_client = httpx.AsyncClient
    def manager_client(**kwargs):
        return real_client(**kwargs, transport=httpx.ASGITransport(app=manager.app))
    monkeypatch.setattr('app_runtime.agent_tools.httpx.AsyncClient', manager_client)
    holder = SimpleNamespace(token=AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE]))
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: holder.token)
    mcp = build_server(db, PROVIDERS)

    async def call(tool, arguments):
        async with Client(mcp) as client:
            return await client.call_tool(tool, arguments)

    async def listed():
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    return SimpleNamespace(db=db, holder=holder, call=call, listed=listed)


def unchanged(db, settings):
    assert db.commits == 0 and not db.receipts and db.settings == settings
    assert not db.beli_receipts and not db.beli_writes
    assert not any(row['owner_user_id'] == db.user.id for row in db.beli_accounts)
    assert not db.resy_receipts and not db.resy_sends
    assert not db.espn_receipts and not espn_fakes.sends(db)


def test_every_registered_tool_has_a_safety_fixture():
    for provider in PROVIDERS:
        assert provider.name in FIXTURES, f'Add a safety fixture for provider {provider.name}.'
        fixture = FIXTURES[provider.name]
        assert set(fixture.args(Database())) == set(provider.tools), f'{provider.name}: arguments for every tool'
        with pytest.MonkeyPatch.context() as monkeypatch:
            db = Database()
            beli_fakes.install(db, monkeypatch)
            resy_fakes.install(db, monkeypatch)
            partiful_fakes.install(db, monkeypatch)
            espn_fakes.install(db, monkeypatch)
            foreign = set(fixture.foreign(db, monkeypatch))
        assert foreign.isdisjoint(fixture.no_resource)
        assert foreign | set(fixture.no_resource) == set(provider.tools), \
            f'{provider.name}: a foreign-resource case or a stated reason for every tool'
        assert all(fixture.no_resource.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', CASES)
async def test_no_token_is_refused(server, provider, tool, level):
    server.holder.token = None
    settings = dict(server.db.settings)
    with pytest.raises(ToolError, match='Sign in to Cozy Commons'):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    unchanged(server.db, settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [case for case in CASES if case.values[2] != 'signin'])
async def test_missing_scope_is_refused(server, provider, tool, level):
    scope = LEVEL_SCOPE[level]
    server.holder.token.scopes.remove(scope)
    settings = dict(server.db.settings)
    with pytest.raises(ToolError, match=f'Reconnect your agent to grant {scope}'):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    unchanged(server.db, settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [case for case in CASES if case.values[2] == 'edit'])
async def test_read_only_token_cannot_call_any_edit_tool(server, provider, tool, level):
    server.holder.token.scopes[:] = [READ_SCOPE]
    with pytest.raises(ToolError, match=EDIT_SCOPE):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    unchanged(server.db, server.db.settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [case for case in CASES if case.values[0].name != COMMONS])
async def test_disabled_project_is_hidden_and_refused(server, provider, tool, level):
    server.db.settings[(server.db.user.id, provider.name)]['enabled'] = False
    settings = {key: dict(value) for key, value in server.db.settings.items()}
    assert tool not in await server.listed()
    with pytest.raises(ToolError, match=rf"not enabled; call enable_project\('{provider.name}'\)"):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    unchanged(server.db, settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [case for case in CASES if case.values[0].name != COMMONS])
async def test_pre_commons_token_reaches_only_its_own_project(server, provider, tool, level):
    server.holder.token.claims = {'_legacy_grants': {'some-other-project': ['read', 'edit']}}
    with pytest.raises(ToolError, match='Reconnect your agent once'):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    unchanged(server.db, server.db.settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [
    case for case in CASES if case.values[0].name not in FIXTURES
    or case.values[1] not in FIXTURES[case.values[0].name].no_resource])
async def test_another_users_resource_is_refused(server, monkeypatch, provider, tool, level):
    fixture = FIXTURES[provider.name]
    foreign = fixture.foreign(server.db, monkeypatch)
    error = fixture.foreign_error if isinstance(fixture.foreign_error, str) else fixture.foreign_error[tool]
    linked_rows = (server.db.beli_accounts + server.db.resy_accounts + server.db.partiful_accounts
                   + server.db.espn_accounts)
    owners = [row['owner_user_id'] for row in linked_rows]
    espn_rows = deepcopy(server.db.espn_tables)
    with pytest.raises(ToolError, match=error):
        await server.call(tool, foreign[tool])
    unchanged(server.db, server.db.settings)
    assert [row['owner_user_id'] for row in linked_rows] == owners
    assert server.db.espn_tables == espn_rows, 'no ESPN proposal may be created or changed for another user'
    others = {row['swid'] for row in server.db.espn_accounts if row['owner_user_id'] != server.db.user.id}
    assert not others & set(server.db.espn_logins), 'no ESPN cookies may be used for another user'
    assert not server.db.beli_logins, 'no Beli login may be decrypted for another user'
    others = {row['email'] for row in server.db.resy_accounts if row['owner_user_id'] != server.db.user.id}
    assert not others & set(server.db.resy_logins), 'no Resy login may be decrypted for another user'
    others = {row['uid'] for row in server.db.partiful_accounts if row['owner_user_id'] != server.db.user.id}
    assert not others & set(server.db.partiful_logins), 'no Partiful session may be used for another user'


@pytest.mark.asyncio
async def test_linked_caller_commits_beli_save_with_only_their_login(server):
    # Another user's linked account sits first, so a lookup that ignores the owner would pick it.
    other, _ = beli_fakes.add_account(server.db, owner=str(uuid4()))
    mine, _ = beli_fakes.add_account(server.db, owner=server.db.user.id)
    save = {**FIXTURES['beli'].args(server.db)['save_restaurant'], 'dry_run': False}
    assert (await server.call('save_restaurant', save)).structured_content['status'] == 'bookmarked'
    assert server.db.beli_logins == [mine['login']]
    assert [login for login, _body in server.db.beli_writes] == [mine['login']]
    assert other['login'] not in server.db.beli_logins


@pytest.mark.asyncio
async def test_linked_caller_books_on_resy_with_only_their_login(server):
    # Another user's linked account sits first, so a lookup that ignores the owner would pick it.
    other, _ = resy_fakes.add_account(server.db, owner=str(uuid4()))
    mine, _ = resy_fakes.add_account(server.db, owner=server.db.user.id)
    preview = (await server.call('book_resy_table', RESY_BOOK)).structured_content
    booked = (await server.call('book_resy_table', {**RESY_BOOK, 'terms_id': preview['terms_id'],
                                                     'dry_run': False})).structured_content
    assert booked['status'] == 'booked' and server.db.resy_sends == [('book', mine['email'])]
    assert set(server.db.resy_logins) == {mine['email']} and other['email'] not in server.db.resy_reservations


@pytest.mark.asyncio
async def test_linked_caller_reads_partiful_with_only_their_session(server):
    # Another user's linked account sits first, so a lookup that ignores the owner would pick it.
    other, _ = partiful_fakes.add_account(server.db, owner=str(uuid4()), label='other')
    mine, _ = partiful_fakes.add_account(server.db, owner=server.db.user.id, label='mine')
    listed = (await server.call('get_partiful_events', {})).structured_content
    assert [event['title'] for event in listed['events']] == ['Synthetic party hosted by mine', 'Synthetic dinner']
    mine_id = server.db.partiful_events[mine['uid']]['hosted'][0]['id']
    detail = (await server.call('get_partiful_events', {'event_id': mine_id})).structured_content
    assert detail['event']['id'] == mine_id
    assert set(server.db.partiful_logins) == {mine['uid']}
    assert {uid for uid, _ in server.db.partiful_reads} == {mine['uid']} and other['uid'] not in repr(listed)


@pytest.mark.asyncio
async def test_linked_caller_approves_espn_change_with_only_their_cookies(server):
    # Another user's linked account sits first, so a lookup that ignores the owner would pick it.
    other, _ = espn_fakes.add_account(server.db, owner=str(uuid4()))
    mine, _ = espn_fakes.add_account(server.db, owner=server.db.user.id)
    proposed = (await server.call('propose_fantasy_change', ESPN_PROPOSE)).structured_content
    assert proposed['status'] == 'pending' and not espn_fakes.sends(server.db)
    approve = {**ESPN_APPROVE, 'proposal_id': proposed['proposal_id'], 'dry_run': False}
    approved = (await server.call('approve_fantasy_change', approve)).structured_content
    assert approved['status'] == 'executed' and espn_fakes.sends(server.db) == [('roster_edit', mine['swid'])]
    assert set(server.db.espn_logins) == {mine['swid']} and other['swid'] not in repr(approved)


@pytest.mark.asyncio
async def test_enabled_project_tools_are_listed(server):
    expected = {tool for provider in PROVIDERS for tool in provider.tools}
    assert await server.listed() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,tool,level', [
    case for case in CASES if case.values[2] == 'edit' and case.values[0].name != COMMONS])
async def test_legacy_edit_needs_its_own_projects_read_grant(server, provider, tool, level):
    # e.g. trips:read + floor-plans:edit must not edit floor plans (it required floor-plans:read too).
    others = {p.name: ['read'] for p in PROVIDERS if p.name not in (COMMONS, provider.name)}
    server.holder.token.claims = {'_legacy_grants': {**others, provider.name: ['edit']}}
    with pytest.raises(ToolError, match='Reconnect your agent once'):
        await server.call(tool, FIXTURES[provider.name].args(server.db)[tool])
    assert tool not in await server.listed()
    unchanged(server.db, server.db.settings)


@pytest.mark.asyncio
async def test_listing_hides_tools_the_token_cannot_call(server):
    server.holder.token.scopes[:] = [READ_SCOPE]
    edit_tools = {case.values[1] for case in CASES if case.values[2] == 'edit'}
    assert not edit_tools & await server.listed()


def test_mounted_servers_are_rejected():
    from fastmcp import FastMCP
    from cc_mcp.server import AgentConfigError, ToolProvider

    def mount(mcp, _context):
        hidden = FastMCP('hidden')

        @hidden.tool
        def mutate() -> str:
            return 'unchecked'
        mcp.mount(hidden)

    rogue = ToolProvider('rogue', mount, tools={})
    with pytest.raises(AgentConfigError, match='mounted'):
        build_server(SimpleNamespace(), (*PROVIDERS, rogue))


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['create', 'restore'])
async def test_apps_snapshot_mutations_require_edit_scope(server, action):
    server.holder.token.scopes[:] = [READ_SCOPE]
    with pytest.raises(ToolError, match=EDIT_SCOPE):
        await server.call('app_backups', {'app': 'foreign', 'action': action,
            'idempotency_key': 'once', 'backup_id': 'a'*32 if action == 'restore' else None,
            'confirm_replace_data': action == 'restore'})


@pytest.mark.asyncio
async def test_apps_reconnect_and_cancel_recheck_resource_and_scope(server):
    for cancel in [False, True]:
        with pytest.raises(ToolError, match='App or job not found'):
            await server.call('exec_command', {'app': 'foreign', 'job_id': 'a'*32, 'cancel': cancel})
    server.holder.token.scopes[:] = [READ_SCOPE]
    with pytest.raises(ToolError, match=EDIT_SCOPE):
        await server.call('exec_command', {'app': 'foreign', 'job_id': 'a'*32, 'cancel': True})


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['create','restore'])
async def test_apps_snapshot_mutations_require_their_own_legacy_read_and_edit_grants(server,action):
    args={'app':'foreign','action':action,'idempotency_key':'once'}
    if action=='restore': args.update(backup_id='a'*32,confirm_replace_data=True)
    for grants in [{'apps':['read'],'trips':['edit']},{'apps':['edit'],'trips':['read']}]:
        server.holder.token.claims={'_legacy_grants':grants}
        with pytest.raises(ToolError,match='Reconnect your agent once'):
            await server.call('app_backups',args)
