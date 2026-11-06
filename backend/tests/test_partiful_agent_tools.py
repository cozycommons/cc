"""Partiful on the shared connector: account link and the read-only events tool."""
import re
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, build_server
from partiful.agent_tools import LINK_STEP, RELINK_STEP
from partiful.partiful_client import PartifulAuthError, PartifulError
from tests import partiful_fakes
from tests.test_commons_agent_tools import Database, connect


@pytest_asyncio.fixture
async def partiful(monkeypatch):
    db = Database()
    partiful_fakes.install(db, monkeypatch)
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    mcp = build_server(db, PROVIDERS)
    _call, listed = connect(mcp)

    async def call(tool, /, **arguments):
        async with Client(mcp) as client:
            return (await client.call_tool(tool, arguments)).structured_content
    return db, call, listed


def enable(db):
    db.settings[(db.user.id, 'partiful')] = {'user_id': db.user.id, 'project_id': 'partiful', 'enabled': True}



async def linked_user(db, call):
    enable(db)
    row, _token = partiful_fakes.add_account(db, owner=db.user.id)  # as the account page links it
    return row


@pytest.mark.asyncio
async def test_new_user_sees_partiful_off_then_the_link_step(partiful):
    db, call, listed = partiful
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['partiful']
    assert project['on_connector'] and project['enabled'] is False and project['linked'] is False
    assert {t['name']: t['access'] for t in project['tools']} == {
        'get_partiful_events': 'read'}
    assert not {'get_partiful_events'} & await listed()
    enabled = await call('enable_project', project_id='partiful')
    assert enabled['linked'] is False and enabled['next_step'] == LINK_STEP
    assert 'Do not ask for the code or a ccp_ token in chat' in LINK_STEP


@pytest.mark.asyncio
async def test_unlinked_user_gets_the_link_step(partiful):
    db, call, _ = partiful
    enable(db)
    partiful_fakes.add_account(db, owner=str(uuid4()))  # someone else's linked account
    with pytest.raises(ToolError, match='Link your Partiful account first: Ask the user to connect Partiful at https://cozycommons.dev/account#partiful'):
        await call('get_partiful_events')
    assert not db.partiful_logins and not db.partiful_reads


@pytest.mark.asyncio
async def test_a_page_linked_account_turns_partiful_on_and_no_token_tool_exists(partiful):
    db, call, listed = partiful
    row, token = partiful_fakes.add_account(db, owner=db.user.id)  # as /account/linked-accounts links it
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['partiful']
    assert project['enabled'] and project['linked'] and project['status']['in_use']
    assert project['enabled_reason'] == 'default: you already use it'
    assert 'link_partiful_account' not in await listed()
    with pytest.raises(ToolError, match='Unknown tool'):
        await call('link_partiful_account', api_token=token)







@pytest.mark.asyncio
async def test_events_list_uses_only_the_callers_session_and_no_guest_lists(partiful):
    db, call, _ = partiful
    other, _ = partiful_fakes.add_account(db, owner=str(uuid4()))
    mine = await linked_user(db, call)
    result = await call('get_partiful_events')
    assert db.partiful_logins == [mine['uid']] and {uid for uid, _ in db.partiful_reads} == {mine['uid']}
    assert [(e['title'], e['scopes'], e['rsvp_status']) for e in result['events']] == [
        ('Synthetic party hosted by synthetic', ['hosted'], None),
        ('Synthetic dinner', ['invited', 'rsvp'], 'GOING')]
    assert result['count'] == 2
    for secret in ('Synthetic Guest', '+15555550100', mine['refresh_token'], mine['uid'], other['uid']):
        assert secret not in repr(result)


@pytest.mark.asyncio
async def test_events_list_filters_by_scope_and_dates(partiful):
    db, call, _ = partiful
    await linked_user(db, call)
    hosted = await call('get_partiful_events', scope='hosted')
    assert [e['title'] for e in hosted['events']] == ['Synthetic party hosted by synthetic']
    later = await call('get_partiful_events', start='2026-11-20', end='2026-11-30')
    assert [e['title'] for e in later['events']] == ['Synthetic dinner']


@pytest.mark.asyncio
async def test_event_details_by_id(partiful):
    db, call, _ = partiful
    mine = await linked_user(db, call)
    event_id = db.partiful_events[mine['uid']]['rsvps'][0]['id']
    result = await call('get_partiful_events', event_id=event_id)
    assert result['event']['id'] == event_id and result['event']['title'] == 'Synthetic dinner'
    assert result['password_required'] is False and 'Synthetic Guest' not in repr(result)


@pytest.mark.asyncio
async def test_event_the_callers_session_cannot_view_is_not_found(partiful):
    db, call, _ = partiful
    other, _ = partiful_fakes.add_account(db, owner=str(uuid4()))
    mine = await linked_user(db, call)
    theirs = db.partiful_events[other['uid']]['hosted'][0]['id']
    with pytest.raises(ToolError, match='Event not found. Call get_partiful_events'):
        await call('get_partiful_events', event_id=theirs)
    assert db.partiful_logins == [mine['uid']]


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [
    {'event_id': 'abc', 'scope': 'hosted'}, {'event_id': 'abc', 'start': '2026-11-01'},
    {'scope': 'everything'}, {'start': '11/01/2026'}, {'event_id': '../secret'}, {'event_id': ' '},
    {'start': '2026-11-30', 'end': '2026-11-01'}])
async def test_event_inputs_are_strict(partiful, arguments):
    db, call, _ = partiful
    await linked_user(db, call)
    with pytest.raises(ToolError):
        await call('get_partiful_events', **arguments)
    assert not db.partiful_reads


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,message', [
    (PartifulAuthError('session expired'), re.escape(RELINK_STEP)),
    (PartifulError('Partiful getMyRsvps -> 500', status=500), r'Partiful did not answer \(HTTP 500\)')])
async def test_partiful_failures_name_the_fix(partiful, failure, message):
    db, call, _ = partiful
    await linked_user(db, call)
    db.partiful_failure = failure
    with pytest.raises(ToolError, match=message):
        await call('get_partiful_events')
