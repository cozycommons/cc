"""Every tool on /mcp, enumerated from the live registry, passes the same safety gates.

A new provider or tool fails here until it has a fixture below: valid arguments
for each tool, and either arguments that target another user's resource or a
stated reason the tool has none. Calls go through the full server, so the access
middleware, scope checks and the tool's own ownership checks all run.
"""
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
from tests import beli_fakes
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
    # Another user's linked account: the caller is unlinked and holds only that user's token.
    _row, token = beli_fakes.add_account(db, owner=str(uuid4()))
    return {'get_restaurant_recs': {'neighborhood': 'West Village'},
            'save_restaurant': {'name': 'Synthetic Bistro', 'idempotency_key': 'save-1', 'dry_run': False},
            'link_beli_account': {'api_token': token}}


FIXTURES = {
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
                         'save_restaurant': {'name': 'Synthetic Bistro', 'idempotency_key': 'save-1'},
                         'link_beli_account': {'api_token': 'ccb_' + 'x' * 43}},
        foreign=beli_foreign,
        foreign_error={'get_restaurant_recs': 'Link your Beli account first',
                       'save_restaurant': 'Link your Beli account first',
                       'link_beli_account': 'linked to another Commons user'}),
}

CASES = [pytest.param(provider, tool, level, id=f'{provider.name}.{tool}')
         for provider in PROVIDERS for tool, level in provider.tools.items()]
PROJECTS = [provider for provider in PROVIDERS if provider.name != COMMONS]


@pytest.fixture
def server(monkeypatch):
    db = Database()
    db.user.email_confirmed_at = '2026-01-01T00:00:00Z'
    beli_fakes.install(db, monkeypatch)
    for provider in PROJECTS:
        db.settings[(db.user.id, provider.name)] = {'user_id': db.user.id, 'project_id': provider.name, 'enabled': True}
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


def test_every_registered_tool_has_a_safety_fixture():
    for provider in PROVIDERS:
        assert provider.name in FIXTURES, f'Add a safety fixture for provider {provider.name}.'
        fixture = FIXTURES[provider.name]
        assert set(fixture.args(Database())) == set(provider.tools), f'{provider.name}: arguments for every tool'
        with pytest.MonkeyPatch.context() as monkeypatch:
            db = Database()
            beli_fakes.install(db, monkeypatch)
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
    owners = [row['owner_user_id'] for row in server.db.beli_accounts]
    with pytest.raises(ToolError, match=error):
        await server.call(tool, foreign[tool])
    unchanged(server.db, server.db.settings)
    assert [row['owner_user_id'] for row in server.db.beli_accounts] == owners
    assert not server.db.beli_logins, 'no Beli login may be decrypted for another user'


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
