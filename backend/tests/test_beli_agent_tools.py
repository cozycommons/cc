"""Beli on the shared connector: account link, strict tools, dry runs and receipts."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, build_server
from ig_logger.sinks.beli.agent_tools import LINK_STEP
from ig_logger.sinks.beli.beli_client import BeliError, BeliUnauthorized
from tests import beli_fakes
from tests.test_commons_agent_tools import Database, connect


@pytest_asyncio.fixture
async def beli(monkeypatch):
    db = Database()
    beli_fakes.install(db, monkeypatch)
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    mcp = build_server(db, PROVIDERS)
    _call, listed = connect(mcp)

    async def call(tool, /, **arguments):  # tools take a `name` argument
        async with Client(mcp) as client:
            return (await client.call_tool(tool, arguments)).structured_content
    return db, token, call, listed


def enable(db):
    db.settings[(db.user.id, 'beli')] = {'user_id': db.user.id, 'project_id': 'beli', 'enabled': True}



async def linked_user(db, call):
    enable(db)
    row, _token = beli_fakes.add_account(db, owner=db.user.id)  # as the account page links it
    return row


SAVE = {'name': 'Synthetic Bistro', 'idempotency_key': 'save-1'}


@pytest.mark.asyncio
async def test_new_user_sees_beli_off_then_the_link_step(beli):
    db, _, call, listed = beli
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['beli']
    assert project['on_connector'] and project['enabled'] is False and project['linked'] is False
    assert project['status']['in_use'] is False
    assert {t['name']: t['access'] for t in project['tools']} == {
        'get_restaurant_recs': 'read', 'save_restaurant': 'edit'}
    assert not {'get_restaurant_recs', 'save_restaurant'} & await listed()
    enabled = await call('enable_project', project_id='beli')
    assert enabled['linked'] is False and enabled['next_step'] == LINK_STEP
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['beli']
    assert project['next_step'] == LINK_STEP and 'cozycommons.dev/account#beli' in project['next_step']
    assert 'Do not ask for their Beli password or a ccb_ token' in LINK_STEP


@pytest.mark.asyncio
async def test_a_page_linked_account_turns_beli_on_and_no_token_tool_exists(beli):
    db, _, call, listed = beli
    row, token = beli_fakes.add_account(db, owner=db.user.id)  # as /account/linked-accounts links it
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['beli']
    assert project['enabled'] and project['linked'] and project['status']['in_use']
    assert project['enabled_reason'] == 'default: you already use it'
    assert 'link_beli_account' not in await listed()
    with pytest.raises(ToolError, match='Unknown tool'):
        await call('link_beli_account', api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,arguments', [('get_restaurant_recs', {'neighborhood': 'West Village'}),
                                            ('save_restaurant', {**SAVE, 'dry_run': False})])
async def test_unlinked_user_gets_the_link_step(beli, tool, arguments):
    db, _, call, _ = beli
    enable(db)
    beli_fakes.add_account(db, owner=str(uuid4()))  # someone else's linked account
    with pytest.raises(ToolError, match='Link your Beli account first: Ask the user to connect Beli at https://cozycommons.dev/account#beli'):
        await call(tool, **arguments)
    assert not db.beli_logins and not db.beli_writes and not db.beli_receipts







@pytest.mark.asyncio
async def test_recs_use_only_the_callers_linked_login(beli):
    db, _, call, _ = beli
    other, _ = beli_fakes.add_account(db, owner=str(uuid4()))
    mine = await linked_user(db, call)
    result = await call('get_restaurant_recs', neighborhood='West Village', day='saturday', time='19:00')
    assert db.beli_logins == [mine['login']] and other['login'] not in db.beli_logins
    assert [(r['id'], r['name'], r['source']) for r in result['recs']] == [
        (501, 'Synthetic Bistro', 'trending'), (502, 'Synthetic Noodles', 'trending')]
    assert result['time'] == '19:00' and result['table_size'] == 2
    assert 'password' not in repr(result) and mine['login'] not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [
    {'neighborhood': 'West Village', 'time': '7pm'}, {'neighborhood': 'West Village', 'day': 'someday'},
    {'neighborhood': 'West Village', 'table_size': '2'}, {'neighborhood': 'West Village', 'limit': 21},
    {'neighborhood': ' '}])
async def test_recs_inputs_are_strict(beli, arguments):
    db, _, call, _ = beli
    await linked_user(db, call)
    with pytest.raises(ToolError):
        await call('get_restaurant_recs', **arguments)
    assert not db.beli_logins


@pytest.mark.asyncio
async def test_save_dry_run_writes_nothing(beli):
    db, _, call, _ = beli
    await linked_user(db, call)
    preview = await call('save_restaurant', **SAVE)
    assert preview['dry_run'] is True and preview['status'] == 'would_bookmark'
    assert preview['business']['id'] == 501
    assert not db.beli_writes and not db.beli_receipts


@pytest.mark.asyncio
async def test_save_commit_replay_and_mismatched_key(beli):
    db, _, call, _ = beli
    await linked_user(db, call)
    saved = await call('save_restaurant', **SAVE, dry_run=False)
    assert saved == {'dry_run': False, 'status': 'bookmarked', 'name': 'Synthetic Bistro',
                     'business': {'id': 501, 'name': 'Synthetic Bistro', 'neighborhood': 'West Village'}}
    assert len(db.beli_writes) == 1
    assert await call('save_restaurant', **SAVE, dry_run=False) == saved  # replay: original result
    assert len(db.beli_writes) == 1
    with pytest.raises(ToolError, match='used with different details. Use a new key'):
        await call('save_restaurant', **SAVE, city='Brooklyn', dry_run=False)
    # A new key for the same place reports it as already saved, never a duplicate.
    again = await call('save_restaurant', name='Synthetic Bistro', idempotency_key='save-2', dry_run=False)
    assert again['status'] == 'already_bookmarked' and len(db.beli_writes) == 1


@pytest.mark.asyncio
async def test_ambiguous_save_writes_nothing_and_frees_the_key(beli):
    db, _, call, _ = beli
    await linked_user(db, call)
    result = await call('save_restaurant', name='Synthetic Cafe', idempotency_key='save-1', dry_run=False)
    assert result['status'] == 'ambiguous' and len(result['candidates']) == 2
    assert not db.beli_writes and not db.beli_receipts
    saved = await call('save_restaurant', name='Synthetic Bistro', idempotency_key='save-1', dry_run=False)
    assert saved['status'] == 'bookmarked'


def reserve(db, row, age):
    """A reservation left by a save with no recorded outcome."""
    db.beli_receipts[(db.user.id, 'save-1')] = {
        'user_id': db.user.id, 'idempotency_key': 'save-1', 'result': None,
        'payload': {'account_id': row['id'], 'name': 'Synthetic Bistro', 'city': None},
        'created_at': (datetime.now(timezone.utc) - age).isoformat()}


@pytest.mark.asyncio
@pytest.mark.parametrize('age', [timedelta(0), timedelta(minutes=5), timedelta(days=1)])
async def test_unsettled_reservation_is_never_written_twice_whatever_its_age(beli, age):
    # Age does not show the earlier save stopped; while Beli lacks the place, the key stays blocked.
    db, _, call, _ = beli
    reserve(db, await linked_user(db, call), age)
    with pytest.raises(ToolError, match='Beli does not show Synthetic Bistro') as error:
        await call('save_restaurant', **SAVE, dry_run=False)
    assert 'same idempotency_key' in str(error.value) and 'new' not in str(error.value)
    assert not db.beli_writes and db.beli_receipts[(db.user.id, 'save-1')]['result'] is None


@pytest.mark.asyncio
async def test_unsettled_reservation_settles_when_beli_shows_the_place(beli):
    db, _, call, _ = beli
    row = await linked_user(db, call)
    reserve(db, row, timedelta(minutes=5))
    db.beli_writes.append((row['login'], {'business_id': 501}))  # the earlier save landed
    saved = await call('save_restaurant', **SAVE, dry_run=False)
    assert saved == {'dry_run': False, 'status': 'bookmarked', 'name': 'Synthetic Bistro',
                     'business': {'id': 501, 'name': 'Synthetic Bistro', 'neighborhood': 'West Village'}}
    assert len(db.beli_writes) == 1 and db.beli_receipts[(db.user.id, 'save-1')]['result'] == saved
    assert await call('save_restaurant', **SAVE, dry_run=False) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [TimeoutError('timed out'), BeliError('Beli POST -> 502', status=502)])
async def test_unconfirmed_write_keeps_the_key_and_settles_on_retry(beli, failure):
    db, _, call, _ = beli
    await linked_user(db, call)
    db.beli_after_write = failure
    with pytest.raises(ToolError, match='may have landed. Call save_restaurant again with the same idempotency_key'):
        await call('save_restaurant', **SAVE, dry_run=False)
    assert len(db.beli_writes) == 1 and db.beli_receipts[(db.user.id, 'save-1')]['result'] is None
    db.beli_after_write = None
    saved = await call('save_restaurant', **SAVE, dry_run=False)
    assert saved['status'] == 'bookmarked' and len(db.beli_writes) == 1
    assert db.beli_receipts[(db.user.id, 'save-1')]['result'] == saved


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,message', [
    (BeliError('Beli GET /api -> 503', status=503), r'Beli did not answer \(HTTP 503\)'),
    (BeliUnauthorized('unauthorized', status=401), 'sign in to Beli again at https://cozycommons.dev/account#beli')])
async def test_beli_failures_name_the_fix_and_release_the_key(beli, failure, message):
    db, _, call, _ = beli
    await linked_user(db, call)
    db.beli_failure = failure
    with pytest.raises(ToolError, match=message):
        await call('save_restaurant', **SAVE, dry_run=False)
    assert not db.beli_receipts and not db.beli_writes
    db.beli_failure = None
    assert (await call('save_restaurant', **SAVE, dry_run=False))['status'] == 'bookmarked'
