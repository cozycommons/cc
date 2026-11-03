"""Agent tool auth, exact money, dry runs, durable retry protocol and registry."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from key_value.aio.stores.memory import MemoryStore

from cc_mcp import commons_tools
from cc_mcp.server import ToolContext, ToolProvider, AgentConfigError, create_agent_app
from trips import agent_tools
from trips.ledger import new_group, apply_command
from tests.test_cc_mcp import settings_environment


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, {}
        self.head = False

    def select(self, *args, **kwargs):
        self.head = kwargs.get('head', False)
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def contains(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *args, **kwargs):
        return self

    def in_(self, *args):
        return self

    def is_(self, *args):
        return self

    def execute(self):
        if self.table == 'trips_groups':
            data = [self.db.row]
        elif self.table == 'trips_agent_receipts':
            data = [{'user_id': uid, 'idempotency_key': key, **receipt}
                    for (uid, key), receipt in self.db.receipts.items()]
        else:
            data = []
        data = [deepcopy(row) for row in data if all(
            set(value) <= set(row[key]) if isinstance(value, list) else row.get(key) == value
            for key, value in self.filters.items())]
        return SimpleNamespace(data=[] if self.head else data, count=len(data))


class Database:
    def __init__(self):
        self.user = SimpleNamespace(id=str(uuid4()), email='synthetic@example.test', user_metadata={'name': 'Sam'})
        self.auth = SimpleNamespace(get_user=lambda _: SimpleNamespace(user=self.user),
            admin=SimpleNamespace(get_user_by_id=lambda _: SimpleNamespace(user=self.user)))
        self.row = new_group(str(uuid4()), self.user.id, 'Synthetic trip', 'USD', 'Sam')
        for name in ('Alex', 'Jamie'):
            self.row, _ = apply_command(self.row, self.user.id, 'add_member', {'name': name, 'revision': self.row['revision']})
        self.receipts, self.commits, self.conflicts = {}, 0, 0

    def table(self, table):
        return Query(self, table)

    def rpc(self, name, args):
        assert name == 'trips_agent_commit'
        self.commits += 1
        if self.conflicts:
            self.conflicts -= 1
            self.row['revision'] += 1
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={'error': 'revision'}))
        self.row = deepcopy(args['p_after'])
        result = deepcopy(args['p_result'])
        self.receipts[(args['p_user_id'], args['p_key'])] = {'payload': deepcopy(args['p_payload']), 'result': result}
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={'result': result}))


@pytest_asyncio.fixture
async def tools(monkeypatch):
    db = Database()
    token = AccessToken(token='synthetic', client_id='test', scopes=['trips:read', 'trips:edit'])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    mcp = FastMCP('test')
    context = ToolContext(db)
    commons_tools.register_tools(mcp, context)
    agent_tools.register_tools(mcp, context)
    registered = await mcp.get_tools()

    async def call(name, **kwargs):
        result = await registered[name].run(kwargs)
        return result.structured_content

    return db, token, call


def expense_args(db, **overrides):
    ids = [m['id'] for m in db.row['data']['members']]
    return {'trip_id': db.row['id'], 'description': 'Dinner', 'total_cents': 10001,
            'payers': [{'member_id': ids[0], 'amount_cents': 10001}],
            'member_ids': ids[::-1], 'idempotency_key': 'expense-1', **overrides}


def repayment_args(db, **overrides):
    ids = [m['id'] for m in db.row['data']['members']]
    return {'trip_id': db.row['id'], 'from_member_id': ids[1], 'to_member_id': ids[0],
            'amount_cents': 100, 'idempotency_key': 'repayment-1', **overrides}


@pytest.mark.asyncio
async def test_whoami_and_extensible_registry_without_feature_scopes(tools):
    db, token, call = tools
    token.scopes.clear()
    assert await call('whoami') == {'id': db.user.id, 'email': db.user.email, 'display_name': 'Sam'}
    projects = {p['id']: p for p in (await call('list_projects'))['projects']}
    assert {'trips', 'floor-planner', 'dice', 'beli', 'resy', 'partiful', 'espn', 'fantasy', 'crowdset', 'design'} == set(projects)
    assert projects['trips']['status']['trip_count'] == 1
    assert projects['floor-planner']['status']['setup'] is False
    assert all(p['status']['next_step'] for p in projects.values())
    assert projects['beli']['on_connector'] is False
    assert '/beli/mcp' in projects['beli']['status']['next_step']


@pytest.mark.asyncio
async def test_registry_failure_is_best_effort(tools, monkeypatch):
    db, _, call = tools
    def unavailable(*args):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(db, 'table', unavailable)
    result = await call('list_projects')
    assert result['projects'][0]['status']['setup'] == 'unknown'


@pytest.mark.asyncio
async def test_overview_lists_and_settlement_links(tools):
    db, _, call = tools
    assert (await call('get_trip_overview'))['trips'][0]['member_count'] == 3
    await call('add_expense', **expense_args(db, dry_run=False))
    # Guest handles are kept on the trip, account handles use the account profile.
    db.row['data']['members'][1]['venmo_username'] = 'alex-test'
    db.user.user_metadata['venmo_username'] = 'sam-test'
    result = await call('get_trip_overview', trip_id=db.row['id'])
    assert sum(result['balances_cents'].values()) == 0
    assert len(result['payments']) == 2
    assert any(p['pay_url'] and 'txn=pay' in p['pay_url'] for p in result['payments'])
    assert any(p['request_url'] and 'txn=charge' in p['request_url'] for p in result['payments'])
    db.row['data']['currency'] = 'EUR'
    assert all(p['pay_url'] is None for p in (await call('get_trip_overview', trip_id=db.row['id']))['payments'])


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['whoami', 'list_projects', 'get_trip_overview', 'add_expense', 'record_repayment'])
async def test_unauthenticated_denied(tools, monkeypatch, tool):
    db, _, call = tools
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: None)
    args = expense_args(db) if tool == 'add_expense' else repayment_args(db) if tool == 'record_repayment' else {}
    with pytest.raises(ToolError, match='Sign in'):
        await call(tool, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,scope', [('get_trip_overview', 'trips:read'), ('add_expense', 'trips:edit'), ('record_repayment', 'trips:edit')])
async def test_missing_scope_names_reconnect_fix(tools, tool, scope):
    db, token, call = tools
    token.scopes.remove(scope)
    args = expense_args(db) if tool == 'add_expense' else repayment_args(db) if tool == 'record_repayment' else {}
    with pytest.raises(ToolError, match=f'Reconnect to grant {scope}'):
        await call(tool, **args)
    assert not db.commits


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['get_trip_overview', 'add_expense', 'record_repayment'])
async def test_cross_trip_denied(tools, tool):
    db, _, call = tools
    db.row['member_user_ids'] = [str(uuid4())]
    args = expense_args(db, dry_run=False) if tool == 'add_expense' else repayment_args(db, dry_run=False) if tool == 'record_repayment' else {'trip_id': db.row['id']}
    with pytest.raises(ToolError, match='not a member'):
        await call(tool, **args)
    assert not db.commits


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['add_expense', 'record_repayment'])
async def test_preview_commit_replay_and_mismatched_key(tools, tool):
    db, _, call = tools
    args = expense_args(db) if tool == 'add_expense' else repayment_args(db)
    before = deepcopy(db.row)
    preview = await call(tool, **args)
    assert preview['dry_run'] is True and db.row == before and not db.receipts
    saved = await call(tool, **args, dry_run=False)
    assert saved['dry_run'] is False and db.commits == 1
    assert await call(tool, **args, dry_run=False) == saved
    assert db.commits == 1
    changed = {**args, 'total_cents': 42} if tool == 'add_expense' else {**args, 'amount_cents': 42}
    with pytest.raises(ToolError, match='different details'):
        await call(tool, **changed, dry_run=False)
    # Replays survive subsequent REST deletion/editing and retain the original receipt.
    db.row['data']['expenses' if tool == 'add_expense' else 'repayments'].clear()
    assert await call(tool, **args, dry_run=False) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize('conflicts', [1, 2])
async def test_revision_conflict_retries_once(tools, conflicts):
    db, _, call = tools
    db.conflicts = conflicts
    if conflicts == 2:
        with pytest.raises(ToolError, match='after one retry'):
            await call('add_expense', **expense_args(db, dry_run=False))
        assert not db.receipts
    else:
        result = await call('add_expense', **expense_args(db, dry_run=False))
        assert result['revision'] == db.row['revision']
    assert db.commits == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,parts,expected', [('even', None, [3334, 3334, 3333]),
    ('percent', [3333, 3333, 3334], [3333, 3333, 3335]), ('exact', [1, 10000, 0], [1, 10000, 0])])
async def test_split_rounding_and_multiple_payers(tools, mode, parts, expected):
    db, _, call = tools
    ids = [m['id'] for m in db.row['data']['members']]
    args = expense_args(db, split_mode=mode, parts=dict(zip(ids, parts)) if parts else None,
        payers=[{'member_id': ids[0], 'amount_cents': 5000}, {'member_id': ids[1], 'amount_cents': 5001}])
    result = await call('add_expense', **args)
    assert result['per_person_cents'] == dict(zip(ids, expected))
    assert sum(result['per_person_cents'].values()) == 10001


@pytest.mark.asyncio
async def test_unknown_names_suggest_exact_member_ids(tools):
    db, _, call = tools
    with pytest.raises(ToolError, match=r'Sam \(id '):
        await call('add_expense', **expense_args(db, member_ids=['Sammy']))
    with pytest.raises(ToolError, match='exact member id'):
        await call('record_repayment', **repayment_args(db, from_member_id=str(uuid4())))


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'total_cents': True}, {'total_cents': 1.5}, {'total_cents': -1},
    {'dry_run': 'false'}, {'parts': {'bad': -1}}, {'payers': []}, {'idempotency_key': ''}])
async def test_strict_input_rejects_unsafe_money(tools, overrides):
    db, _, call = tools
    with pytest.raises(Exception):
        await call('add_expense', **expense_args(db, **overrides))
    assert not db.commits


def test_scopeless_provider_and_nonempty_unique_scope_union():
    app = create_agent_app(object(), providers=(commons_tools.provider, agent_tools.provider),
                           environment=settings_environment(), storage=MemoryStore())
    assert 'Call list_projects first' in app.state.cc_mcp.instructions
    with pytest.raises(AgentConfigError, match='at least one scope'):
        create_agent_app(object(), providers=(commons_tools.provider,), environment=settings_environment(), storage=MemoryStore())


@pytest.mark.asyncio
async def test_sdk_streamable_http_all_tools_with_proxy_token_and_synthetic_storage():
    """Protocol substitute when Docker is unavailable: no DCR/browser OAuth claim."""
    import httpx
    from fastmcp.server.auth.oauth_proxy import JTIMapping, UpstreamTokenSet
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from tests.test_cc_mcp import FixedTokenVerifier, OAUTH_CLIENT_ID

    db = Database()
    app = create_agent_app(db, providers=(commons_tools.provider, agent_tools.provider),
        environment=settings_environment(), token_verifier=FixedTokenVerifier(), storage=MemoryStore())
    oauth = app.state.cc_mcp_oauth
    upstream_id, jti = uuid4().hex, uuid4().hex
    await oauth._upstream_token_store.put(key=upstream_id, value=UpstreamTokenSet(
        upstream_token_id=upstream_id, access_token='upstream-test-access-token', refresh_token=None,
        refresh_token_expires_at=None, expires_at=4_000_000_000, token_type='Bearer', scope='openid email',
        client_id=OAUTH_CLIENT_ID, created_at=1), ttl=3600)
    await oauth._jti_mapping_store.put(key=jti,
        value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1), ttl=3600)
    token = oauth.jwt_issuer.issue_access_token('sdk-test-client', ['trips:read', 'trips:edit'], jti, 3600)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with app.router.lifespan_context(app):
        async with streamablehttp_client('http://127.0.0.1:8000/mcp',
            headers={'Authorization': f'Bearer {token}'}, httpx_client_factory=factory) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert 'Call list_projects first' in initialized.instructions

                async def call(name, **kwargs):
                    result = await session.call_tool(name, kwargs)
                    assert not result.isError, result.content
                    return result.structuredContent

                assert len((await call('list_projects'))['projects']) == 10
                assert (await call('whoami'))['id'] == db.user.id
                assert (await call('get_trip_overview'))['trips'][0]['id'] == db.row['id']
                initial = await call('get_trip_overview', trip_id=db.row['id'])
                expense = expense_args(db)
                assert (await call('add_expense', **expense))['dry_run']
                assert db.row['revision'] == initial['revision']
                saved = await call('add_expense', **expense, dry_run=False)
                assert await call('add_expense', **expense, dry_run=False) == saved
                repayment = repayment_args(db)
                assert (await call('record_repayment', **repayment))['dry_run']
                assert db.row['revision'] == saved['revision']
                repaid = await call('record_repayment', **repayment, dry_run=False)
                assert await call('record_repayment', **repayment, dry_run=False) == repaid
                assert db.row['revision'] == initial['revision'] + 2
