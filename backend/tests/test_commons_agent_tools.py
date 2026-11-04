"""Agent tool auth, exact money, dry runs, durable retry protocol and registry."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
import mcp.types as mt
from key_value.aio.stores.memory import MemoryStore

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, build_server, create_agent_app
from trips.ledger import new_group, apply_command
from tests.test_cc_mcp import settings_environment


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, {}
        self.head = False
        self.write = None
        self.action = None
        self.inserted = self.sort = self.cap = None

    def select(self, *args, **kwargs):
        self.head = kwargs.get('head', False)
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def contains(self, key, value):
        self.filters[key] = value
        return self

    def order(self, column, desc=False):
        self.sort = (column, desc)
        return self

    def limit(self, count):
        self.cap = count
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def in_(self, key, values):
        self.filters[key] = ('in', list(values))
        return self

    def is_(self, key, value):
        if self.table in LINKED_TABLES:
            self.filters[key] = None if value == 'null' else value
        return self

    def upsert(self, row, on_conflict, ignore_duplicates=False):
        self.write = row
        self.ignore_duplicates = ignore_duplicates
        return self

    def update(self, row):
        self.action = ('update', row)
        return self

    def delete(self):
        self.action = ('delete', None)
        return self

    def matches(self, row):
        for key, value in self.filters.items():
            if isinstance(value, tuple):
                if row.get(key) not in value[1]:
                    return False
            elif isinstance(value, list):
                if not set(value) <= set(row[key]):
                    return False
            elif row.get(key) != value:
                return False
        return True

    def execute(self):
        if self.table in LINKED_TABLES:
            return self.db.linked_execute(self)
        if self.table in ESPN_TABLES:
            return self.db.espn_execute(self)
        if self.write is not None:
            assert self.table == 'cc_mcp_project_settings'
            self.db.settings[(self.write['user_id'], self.write['project_id'])] = deepcopy(self.write)
            return SimpleNamespace(data=[self.write])
        if self.table == 'trips_groups':
            data = [self.db.row]
        elif self.table == 'trips_agent_receipts':
            data = [{'user_id': uid, 'idempotency_key': key, **receipt}
                    for (uid, key), receipt in self.db.receipts.items()]
        elif self.table == 'cc_mcp_project_settings':
            data = list(self.db.settings.values())
        else:
            data = []
        data = [deepcopy(row) for row in data if self.matches(row)]
        return SimpleNamespace(data=[] if self.head else data, count=len(data))


LINKED_TABLES = {'beli_accounts': 'beli', 'beli_agent_receipts': 'beli',
                 'resy_accounts': 'resy', 'resy_agent_receipts': 'resy', 'partiful_accounts': 'partiful',
                 'espn_accounts': 'espn', 'espn_agent_receipts': 'espn'}
# ESPN's own gate tables, stored as plain rows (the write-claim trigger is tested on Postgres).
ESPN_TABLES = ('espn_lineup_runs', 'espn_roster_edits', 'espn_trade_proposals', 'espn_snapshots',
               'espn_lineup_approvals')


class Database:
    def __init__(self):
        self.user = SimpleNamespace(id=str(uuid4()), email='synthetic@example.test', user_metadata={'name': 'Sam'})
        self.auth = SimpleNamespace(get_user=lambda _: SimpleNamespace(user=self.user),
            admin=SimpleNamespace(get_user_by_id=lambda _: SimpleNamespace(user=self.user)))
        self.row = new_group(str(uuid4()), self.user.id, 'Synthetic trip', 'USD', 'Sam')
        for name in ('Alex', 'Jamie'):
            self.row, _ = apply_command(self.row, self.user.id, 'add_member', {'name': name, 'revision': self.row['revision']})
        self.receipts, self.commits, self.conflicts = {}, 0, 0
        self.settings = {}
        # Beli, Resy, Partiful and ESPN: account rows (with owner_user_id) and connector receipts.
        self.beli_accounts, self.beli_receipts = [], {}
        self.resy_accounts, self.resy_receipts = [], {}
        self.partiful_accounts = []  # read-only on the connector: no receipts
        self.espn_accounts, self.espn_receipts = [], {}
        self.espn_tables = {name: [] for name in ESPN_TABLES}
        self.clock = datetime.now(timezone.utc)

    def table(self, table):
        return Query(self, table)

    def linked_execute(self, query):
        project = LINKED_TABLES[query.table]
        receipts = getattr(self, f'{project}_receipts', {})
        if query.table.endswith('_accounts'):
            assert query.write is None and query.action is None, f'{project} accounts change only through the link RPC'
            rows = getattr(self, f'{project}_accounts')
        else:
            rows = list(receipts.values())
        if query.write is not None:
            key = (query.write['user_id'], query.write['idempotency_key'])
            if key in receipts:
                assert query.ignore_duplicates
                return SimpleNamespace(data=[])
            receipts[key] = {'result': None, 'created_at': '2026-11-03T12:00:00+00:00', **deepcopy(query.write)}
            return SimpleNamespace(data=[deepcopy(receipts[key])])
        matched = [row for row in rows if query.matches(row)]
        if query.action:
            kind, change = query.action
            assert not (project in ('resy', 'espn') and kind == 'delete'), \
                f'{project} receipts are never released (no DELETE grant)'
            for row in matched:
                key = (row['user_id'], row['idempotency_key'])
                if kind == 'delete':
                    del receipts[key]
                else:
                    receipts[key].update(deepcopy(change))
        return SimpleNamespace(data=[deepcopy(row) for row in matched])

    def espn_execute(self, query):
        rows = self.espn_tables[query.table]
        if query.write is not None:  # a lineup approval claim: one per proposal (0021)
            assert query.table == 'espn_lineup_approvals' and query.ignore_duplicates
            if any(row['proposal_id'] == query.write['proposal_id'] for row in rows):
                return SimpleNamespace(data=[])
            rows.append(deepcopy(query.write))
            return SimpleNamespace(data=[deepcopy(query.write)])
        if query.inserted is not None:
            self.clock += timedelta(milliseconds=1)  # created_at orders rows like now() does
            stamp = 'captured_at' if query.table == 'espn_snapshots' else 'created_at'
            row = {'id': str(uuid4()), stamp: self.clock.isoformat(), **deepcopy(query.inserted)}
            rows.append(row)
            return SimpleNamespace(data=[deepcopy(row)])
        matched = [row for row in rows if query.matches(row)]
        if query.action:
            kind, change = query.action
            assert kind == 'update', 'the connector never deletes ESPN gate rows'
            for row in matched:
                row.update(deepcopy(change))
        if query.sort:
            matched.sort(key=lambda row: row.get(query.sort[0]) or '', reverse=query.sort[1])
        return SimpleNamespace(data=[deepcopy(row) for row in matched[:query.cap]])

    def rpc(self, name, args):
        if name in ('beli_link_account', 'resy_link_account', 'partiful_link_account', 'espn_link_account'):
            rows = getattr(self, name.replace('_link_account', '_accounts'))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=link_account(rows, **args)))
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


def link_account(rows, p_account_id, p_user_id):
    # Mirrors public.beli_link_account (0017), resy_link_account (0018), partiful_link_account (0019)
    # and espn_link_account (0020).
    account = next((row for row in rows if row['id'] == p_account_id), None)
    if account is None:
        return 'missing'
    if account['owner_user_id'] == p_user_id:
        return 'already_linked'
    if account['owner_user_id'] is not None:
        return 'other_owner'
    for row in rows:
        if row['owner_user_id'] == p_user_id:
            row['owner_user_id'] = None
    account['owner_user_id'] = p_user_id
    return 'linked'


def connect(mcp):
    """Call tools through the full server: access middleware included."""
    async def call(name, **kwargs):
        async with Client(mcp) as client:
            return (await client.call_tool(name, kwargs)).structured_content

    async def listed():
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    return call, listed


@pytest_asyncio.fixture
async def tools(monkeypatch):
    db = Database()
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    call, _ = connect(build_server(db, PROVIDERS))
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
    # Existing users keep their projects without a stored choice.
    assert projects['trips']['enabled'] is True and projects['trips']['status']['trip_count'] == 1
    assert projects['trips']['enabled_reason'] == 'default: you already use it'
    assert projects['trips']['next_step'] == 'Call get_trip_overview.'
    assert projects['floor-planner']['enabled'] is False
    assert projects['floor-planner']['next_step'] == "Call enable_project('floor-planner') to add its 4 tools."
    assert {t['name']: t['access'] for t in projects['trips']['tools']} == {
        'get_trip_overview': 'read', 'add_expense': 'edit', 'record_repayment': 'edit'}
    assert all(p['next_step'] for p in projects.values())
    assert projects['beli']['on_connector'] is True and projects['beli']['linked'] is False
    assert projects['beli']['next_step'] == "Call enable_project('beli') to add its 3 tools."
    assert projects['resy']['on_connector'] is True and projects['resy']['linked'] is False
    assert projects['resy']['next_step'] == "Call enable_project('resy') to add its 5 tools."
    assert projects['partiful']['on_connector'] is True and projects['partiful']['linked'] is False
    assert projects['partiful']['next_step'] == "Call enable_project('partiful') to add its 2 tools."
    assert projects['espn']['on_connector'] is True and projects['espn']['linked'] is False
    assert projects['espn']['next_step'] == "Call enable_project('espn') to add its 6 tools."
    # Every project with a separate MCP endpoint is now on the connector.
    assert not [p for p in projects.values() if not p['on_connector'] and 'api_token' in p['next_step']]


@pytest.mark.asyncio
async def test_enable_and_disable_persist_a_choice_and_gate_calls(tools):
    db, _, call = tools
    disabled = await call('disable_project', project_id='trips')
    assert disabled['enabled'] is False and 'enable_project' in disabled['next_step']
    assert db.settings[(db.user.id, 'trips')]['enabled'] is False
    with pytest.raises(ToolError, match=r"Cozy Trips is not enabled; call enable_project\('trips'\)"):
        await call('get_trip_overview')
    projects = {p['id']: p for p in (await call('list_projects'))['projects']}
    assert projects['trips']['enabled'] is False and projects['trips']['enabled_reason'] == 'your choice'
    enabled = await call('enable_project', project_id='trips')
    assert [t['name'] for t in enabled['tools']] == ['get_trip_overview', 'add_expense', 'record_repayment']
    assert all(t['description'] for t in enabled['tools'])
    assert 'refresh the tool list' in enabled['tool_list']
    assert (await call('get_trip_overview'))['trips'][0]['id'] == db.row['id']
    plans = await call('enable_project', project_id='floor-planner')
    assert plans['next_step'].startswith('Create a plan')


@pytest.mark.asyncio
@pytest.mark.parametrize('project_id,message', [('commons', 'Unknown project'), ('nope', 'Unknown project'),
    ('dice', 'no agent tools yet')])
async def test_enable_project_errors_name_the_fix(tools, project_id, message):
    db, _, call = tools
    with pytest.raises(ToolError, match=message):
        await call('enable_project', project_id=project_id)
    assert not db.settings


@pytest.mark.asyncio
async def test_status_failure_is_best_effort_but_settings_failure_fails_closed(tools, monkeypatch):
    db, _, call = tools
    def unavailable(*args):
        raise RuntimeError('unavailable')
    original = db.table
    monkeypatch.setattr(db, 'table', lambda name: unavailable() if name == 'trips_groups' and not db.settings else original(name))
    projects = {p['id']: p for p in (await call('list_projects'))['projects']}
    assert projects['trips']['status']['unavailable'] is True and projects['trips']['enabled'] is False
    monkeypatch.setattr(db, 'table', lambda name: unavailable() if name == 'cc_mcp_project_settings' else original(name))
    with pytest.raises(ToolError, match='Could not check your enabled projects'):
        await call('get_trip_overview')


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
@pytest.mark.parametrize('tool,scope', [('get_trip_overview', READ_SCOPE), ('add_expense', EDIT_SCOPE), ('record_repayment', EDIT_SCOPE)])
async def test_missing_scope_names_reconnect_fix(tools, tool, scope):
    db, token, call = tools
    token.scopes.remove(scope)
    args = expense_args(db) if tool == 'add_expense' else repayment_args(db) if tool == 'record_repayment' else {}
    with pytest.raises(ToolError, match=f'Reconnect your agent to grant {scope}'):
        await call(tool, **args)
    assert not db.commits


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['get_trip_overview', 'add_expense', 'record_repayment'])
async def test_cross_trip_denied(tools, tool):
    db, _, call = tools
    # Enabled by choice, so the request reaches the trip membership check.
    db.settings[(db.user.id, 'trips')] = {'user_id': db.user.id, 'project_id': 'trips', 'enabled': True}
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


def test_connector_instructions_lead_with_discovery():
    app = create_agent_app(object(), providers=PROVIDERS, environment=settings_environment(), storage=MemoryStore())
    assert 'Call list_projects first' in app.state.cc_mcp.instructions
    assert 'enable_project' in app.state.cc_mcp.instructions


@pytest.mark.asyncio
async def test_sdk_streamable_http_all_tools_with_proxy_token_and_synthetic_storage():
    """Protocol substitute when Docker is unavailable: no DCR/browser OAuth claim."""
    import httpx
    from fastmcp.server.auth.oauth_proxy import JTIMapping, UpstreamTokenSet
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from tests.test_cc_mcp import FixedTokenVerifier, OAUTH_CLIENT_ID

    db = Database()
    app = create_agent_app(db, providers=PROVIDERS,
        environment=settings_environment(), token_verifier=FixedTokenVerifier(), storage=MemoryStore())
    oauth = app.state.cc_mcp_oauth
    upstream_id, jti = uuid4().hex, uuid4().hex
    await oauth._upstream_token_store.put(key=upstream_id, value=UpstreamTokenSet(
        upstream_token_id=upstream_id, access_token='upstream-test-access-token', refresh_token=None,
        refresh_token_expires_at=None, expires_at=4_000_000_000, token_type='Bearer', scope='openid email',
        client_id=OAUTH_CLIENT_ID, created_at=1), ttl=3600)
    await oauth._jti_mapping_store.put(key=jti,
        value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1), ttl=3600)
    token = oauth.jwt_issuer.issue_access_token('sdk-test-client', [READ_SCOPE, EDIT_SCOPE], jti, 3600)
    notifications = []

    async def on_message(message):
        if isinstance(message, mt.ServerNotification):
            notifications.append(message.root.method)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with app.router.lifespan_context(app):
        async with streamablehttp_client('http://127.0.0.1:8000/mcp',
            headers={'Authorization': f'Bearer {token}'}, httpx_client_factory=factory) as (read, write, _):
            async with ClientSession(read, write, message_handler=on_message) as session:
                initialized = await session.initialize()
                assert 'Call list_projects first' in initialized.instructions
                assert initialized.capabilities.tools.listChanged is True

                async def listed():
                    return {tool.name for tool in (await session.list_tools()).tools}

                commons = {'whoami', 'list_projects', 'enable_project', 'disable_project'}
                trips = {'get_trip_overview', 'add_expense', 'record_repayment'}
                plans = {'list_floor_plans', 'get_floor_plan', 'describe_floor_plan_schema', 'edit_floor_plan'}
                # Stateless HTTP: filtering runs per request, defaults enable Trips only.
                assert await listed() == commons | trips
                await session.call_tool('enable_project', {'project_id': 'floor-planner'})
                assert notifications == ['notifications/tools/list_changed']
                assert await listed() == commons | trips | plans
                await session.call_tool('disable_project', {'project_id': 'floor-planner'})
                assert await listed() == commons | trips
                hidden = await session.call_tool('list_floor_plans', {})
                assert hidden.isError and "enable_project('floor-planner')" in hidden.content[0].text

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


@pytest.mark.asyncio
async def test_linked_account_projects_require_the_link_step_first(monkeypatch):
    """The M3 contract: project tools resolve the account server-side, after one link step."""
    from cc_mcp.server import AccountLink, ToolProvider

    db = Database()
    accounts = {}

    def register(mcp, context):
        @mcp.tool()
        async def link_example_account(code: str) -> dict:
            user = await context.signed_in_user(context.need_scope(EDIT_SCOPE))
            accounts[user.id] = {'account_id': 'acct-1'}
            return {'linked': True}

        @mcp.tool()
        async def get_example_data() -> dict:
            user = await context.signed_in_user(context.need_scope(READ_SCOPE))
            return {'account_id': accounts[user.id]['account_id']}

    linked = ToolProvider(
        'example', register, {'link_example_account': 'edit', 'get_example_data': 'read'},
        title='Example', status=lambda client, user: {'in_use': user.id in accounts},
        link=AccountLink('Call link_example_account(code) with the code from https://example.test/link.',
                         linked=lambda client, user: accounts.get(user.id), tool='link_example_account'))
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    call, listed = connect(build_server(db, (*PROVIDERS, linked)))
    assert 'get_example_data' not in await listed()
    enabled = await call('enable_project', project_id='example')
    assert enabled['linked'] is False and enabled['next_step'].startswith('Call link_example_account')
    assert {'link_example_account', 'get_example_data'} <= await listed()
    with pytest.raises(ToolError, match='Link your Example account first: Call link_example_account'):
        await call('get_example_data')
    project = next(p for p in (await call('list_projects'))['projects'] if p['id'] == 'example')
    assert project['linked'] is False and project['next_step'].startswith('Call link_example_account')
    assert await call('link_example_account', code='one-time') == {'linked': True}
    assert await call('get_example_data') == {'account_id': 'acct-1'}
