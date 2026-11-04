"""ESPN on the shared connector: account link, merged reads, propose -> approve and at-most-once approvals."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, build_server
from espn import agent_tools
from espn.agent_tools import LINK_STEP, RELINK_STEP, UNCONFIRMED, UNSETTLED
from espn.espn_client import EspnAuthError
from tests import espn_fakes
from tests.espn_fakes import BENCHED, DROP, FREE_AGENT, IDLE, OWN_TEAM, RIVAL_STAR, RIVAL_TEAM, sends
from tests.test_commons_agent_tools import Database, connect

EDIT = {'kind': 'roster_edit', 'add_player_id': FREE_AGENT, 'drop_player_id': DROP}


@pytest_asyncio.fixture
async def espn(monkeypatch):
    db = Database()
    espn_fakes.install(db, monkeypatch)
    monkeypatch.setattr(agent_tools, '_LINK_ATTEMPTS', {})
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    call, listed = connect(build_server(db, PROVIDERS))
    return db, call, listed


async def linked_user(db, call):
    db.settings[(db.user.id, 'espn')] = {'user_id': db.user.id, 'project_id': 'espn', 'enabled': True}
    row, token = espn_fakes.add_account(db)
    await call('link_espn_account', api_token=token)
    return row


def league(db, row):
    return db.espn_leagues[row['swid']]


async def approve(call, kind, proposal_id, key='approve-1', dry_run=False):
    return await call('approve_fantasy_change', kind=kind, proposal_id=proposal_id, idempotency_key=key,
                      dry_run=dry_run)


# Linking

@pytest.mark.asyncio
async def test_new_user_sees_espn_off_and_every_tool_needs_the_link(espn):
    db, call, _listed = espn
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['espn']
    assert project['on_connector'] and project['enabled'] is False and project['linked'] is False
    assert {t['name']: t['access'] for t in project['tools']} == {
        'get_fantasy_league': 'read', 'get_fantasy_trends': 'read', 'get_fantasy_activity': 'read',
        'propose_fantasy_change': 'edit', 'approve_fantasy_change': 'edit', 'link_espn_account': 'edit'}
    enabled = await call('enable_project', project_id='espn')
    assert enabled['next_step'] == LINK_STEP
    with pytest.raises(ToolError, match='link_espn_account'):
        await call('get_fantasy_league')


@pytest.mark.asyncio
async def test_link_never_echoes_the_token_refuses_other_owners_and_replaces_your_own(espn):
    db, call, _listed = espn
    first = await linked_user(db, call)
    assert first['owner_user_id'] == db.user.id
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['espn']
    assert project['linked'] is True and project['status']['in_use'] is True
    theirs, their_token = espn_fakes.add_account(db, owner='another-user')
    with pytest.raises(ToolError, match='linked to another Commons user'):
        await call('link_espn_account', api_token=their_token)
    with pytest.raises(ToolError, match='No ESPN account matches'):
        await call('link_espn_account', api_token='cce_' + 'x' * 43)
    second, token = espn_fakes.add_account(db, label='second')
    result = await call('link_espn_account', api_token=token)
    assert result['replaced_account']['id'] == first['id'] and token not in repr(result)
    assert first['owner_user_id'] is None and second['owner_user_id'] == db.user.id
    assert theirs['owner_user_id'] == 'another-user' and not db.espn_logins  # linking decrypts nothing


# Reads

@pytest.mark.asyncio
async def test_league_views_default_to_your_own_team(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    overview = await call('get_fantasy_league')
    assert overview['your_team_id'] == OWN_TEAM and {t['team_id'] for t in overview['teams']} == {OWN_TEAM, RIVAL_TEAM}
    mine = await call('get_fantasy_league', view='team')
    rival = await call('get_fantasy_league', view='team', team_id=RIVAL_TEAM)
    assert mine['team']['team_id'] == OWN_TEAM and rival['team']['team_id'] == RIVAL_TEAM
    assert (await call('get_fantasy_league', view='standings'))['count'] == 2
    with pytest.raises(ToolError, match="No team 99 in your league"):
        await call('get_fantasy_league', view='team', team_id=99)
    with pytest.raises(ToolError, match="team_id is only for view='team'"):
        await call('get_fantasy_league', view='standings', team_id=RIVAL_TEAM)
    assert 'teams' in await call('get_fantasy_trends', kind='teams')
    assert not sends(db)


@pytest.mark.asyncio
async def test_expired_cookies_ask_to_onboard_again(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    db.espn_failure = EspnAuthError('ESPN league -> 401', status=401)
    with pytest.raises(ToolError) as error:
        await call('get_fantasy_league')
    assert str(error.value) == RELINK_STEP


# Roster edits and trades

@pytest.mark.asyncio
async def test_propose_sends_nothing_and_rejects_arguments_of_another_kind(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    with pytest.raises(ToolError, match="add_player_id do not apply to kind='trade'"):
        await call('propose_fantasy_change', kind='trade', add_player_id=FREE_AGENT)
    proposed = await call('propose_fantasy_change', **EDIT)
    assert proposed['status'] == 'pending' and 'Add Synthetic Player 9001' in proposed['summary']
    assert proposed['next_step'].startswith('Nothing was sent to ESPN')
    preview = await approve(call, 'roster_edit', proposed['proposal_id'], dry_run=True)
    assert preview['status'] == 'would_approve' and preview['summary'] == proposed['summary']
    assert not sends(db) and not db.espn_receipts


@pytest.mark.asyncio
async def test_roster_edit_approves_once_replays_and_refuses_key_reuse(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    edit = await call('propose_fantasy_change', **EDIT)
    done = await approve(call, 'roster_edit', edit['proposal_id'])
    assert done['status'] == 'executed' and done['summary'].startswith('Roster edit executed: Add')
    assert await approve(call, 'roster_edit', edit['proposal_id']) == done
    other = await call('propose_fantasy_change', kind='roster_edit', drop_player_id=BENCHED)
    with pytest.raises(ToolError, match='already used for: Roster edit executed'):
        await approve(call, 'roster_edit', other['proposal_id'])
    with pytest.raises(ToolError, match='is already executed'):
        await approve(call, 'roster_edit', edit['proposal_id'], key='approve-2')
    assert [kind for kind, _swid in sends(db)] == ['roster_edit']


@pytest.mark.asyncio
async def test_lost_answer_is_settled_only_by_reading_espn(espn):
    db, call, _listed = espn
    row = await linked_user(db, call)
    edit = await call('propose_fantasy_change', **EDIT)
    league(db, row).answer_lost = league(db, row).hidden = True  # ESPN took it; reads lag behind
    with pytest.raises(ToolError, match=r'not confirmed: ESPN does not show the roster edit yet \(it is uncertain\)'):
        await approve(call, 'roster_edit', edit['proposal_id'])
    with pytest.raises(ToolError, match='not confirmed'):
        await approve(call, 'roster_edit', edit['proposal_id'])
    with pytest.raises(ToolError, match='is uncertain: ESPN may already have it'):
        await approve(call, 'roster_edit', edit['proposal_id'], key='approve-2')
    league(db, row).reveal()
    settled = await approve(call, 'roster_edit', edit['proposal_id'])
    assert settled['status'] == 'executed' and settled['confirmed_from'] == 'ESPN'
    assert await approve(call, 'roster_edit', edit['proposal_id']) == settled
    assert [kind for kind, _swid in sends(db)] == ['roster_edit']
    assert (db.user.id, 'approve-2') not in db.espn_receipts  # refused before its key was reserved


@pytest.mark.asyncio
async def test_approval_that_never_claims_spends_the_key_and_sends_nothing(espn):
    db, call, _listed = espn
    row = await linked_user(db, call)
    first = await call('propose_fantasy_change', **EDIT)
    second = await call('propose_fantasy_change', kind='roster_edit', drop_player_id=DROP)
    league(db, row).answer_lost = league(db, row).hidden = True
    with pytest.raises(ToolError, match='not confirmed'):
        await approve(call, 'roster_edit', first['proposal_id'])
    # The overlapping edit is refused before its claim, so nothing reaches ESPN under this key.
    with pytest.raises(ToolError, match='unresolved ESPN write .* Nothing was sent to ESPN'):
        await approve(call, 'roster_edit', second['proposal_id'], key='approve-2')
    with pytest.raises(ToolError, match='Nothing was sent to ESPN under this idempotency_key'):
        await approve(call, 'roster_edit', second['proposal_id'], key='approve-2')
    assert [kind for kind, _swid in sends(db)] == ['roster_edit']


@pytest.mark.asyncio
async def test_expired_and_unknown_proposals_are_refused_before_any_key_is_spent(espn):
    db, call, _listed = espn
    row = await linked_user(db, call)
    stale = espn_fakes.add_edit(db, row, minutes=-1)
    with pytest.raises(ToolError, match='expired at .* Propose it again'):
        await approve(call, 'roster_edit', stale['id'])
    with pytest.raises(ToolError, match='No trade offer .* in your ESPN account'):
        await approve(call, 'trade', stale['id'])
    assert not db.espn_receipts and not sends(db)


@pytest.mark.asyncio
async def test_trade_offer_is_submitted_once(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    offer = await call('propose_fantasy_change', kind='trade', counterparty_team_id=RIVAL_TEAM,
                       give_player_ids=[DROP], receive_player_ids=[RIVAL_STAR])
    assert 'approving submits this offer to ESPN' in offer['summary']
    done = await approve(call, 'trade', offer['proposal_id'])
    assert done['status'] == 'offered' and 'accepts or declines on ESPN' in done['note']
    assert await approve(call, 'trade', offer['proposal_id']) == done
    listed = await call('get_fantasy_activity', kind='trades')
    assert [p['status'] for p in listed['proposals']] == ['offered']
    assert [kind for kind, _swid in sends(db)] == ['trade']


# Lineups

@pytest.mark.asyncio
async def test_lineup_preview_then_one_live_run(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    plan = await call('propose_fantasy_change', kind='lineup')
    assert f'Synthetic Player {BENCHED} bench -> UTIL' in plan['summary']
    assert f'Synthetic Player {IDLE} UTIL -> bench' in plan['summary']
    done = await approve(call, 'lineup', plan['proposal_id'])
    assert done['status'] == 'ok' and done['run']['mode'] == 'live'
    assert await approve(call, 'lineup', plan['proposal_id']) == done
    runs = await call('get_fantasy_activity', kind='lineup_runs')
    assert [run['mode'] for run in runs['runs']] == ['live', 'dry_run']
    again = await call('propose_fantasy_change', kind='lineup')
    assert 'no moves needed' in again['summary']
    with pytest.raises(ToolError, match='is not a lineup preview'):
        await approve(call, 'lineup', done['run']['id'], key='approve-2')
    assert [kind for kind, _swid in sends(db)] == ['lineup']


@pytest.mark.asyncio
async def test_old_lineup_preview_is_refused(espn):
    db, call, _listed = espn
    await linked_user(db, call)
    plan = await call('propose_fantasy_change', kind='lineup')
    old = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    db.espn_tables['espn_lineup_runs'][0]['created_at'] = old
    with pytest.raises(ToolError, match='older than 30 minutes'):
        await approve(call, 'lineup', plan['proposal_id'])
    assert not db.espn_receipts and not sends(db)


@pytest.mark.asyncio
async def test_unrecorded_lineup_run_settles_from_the_espn_lineup(espn, monkeypatch):
    db, call, _listed = espn
    await linked_user(db, call)
    plan = await call('propose_fantasy_change', kind='lineup')
    real_send = agent_tools.send

    def lost(*args):
        real_send(*args)
        raise TimeoutError('answer lost after ESPN applied the lineup')
    monkeypatch.setattr(agent_tools, 'send', lost)
    with pytest.raises(ToolError, match='ESPN did not confirm the lineup'):
        await approve(call, 'lineup', plan['proposal_id'])
    settled = await approve(call, 'lineup', plan['proposal_id'])
    assert settled['status'] == 'set' and settled['confirmed_from'] == 'your ESPN lineup'
    assert [kind for kind, _swid in sends(db)] == ['lineup']


@pytest.mark.asyncio
async def test_lineup_proposal_is_submitted_once_whatever_the_key(espn):
    db, call, _listed = espn
    row = await linked_user(db, call)
    plan = await call('propose_fantasy_change', kind='lineup')
    league(db, row).hidden = True  # ESPN took the moves; reads still show the old lineup
    first = await approve(call, 'lineup', plan['proposal_id'])
    again = await approve(call, 'lineup', plan['proposal_id'], key='approve-2')
    assert [kind for kind, _swid in sends(db)] == ['lineup']
    assert again == first and await approve(call, 'lineup', plan['proposal_id'], key='approve-2') == first
    assert [(c['proposal_id'], c['idempotency_key']) for c in db.espn_tables['espn_lineup_approvals']] == [
        (plan['proposal_id'], 'approve-1')]


@pytest.mark.asyncio
async def test_concurrent_lineup_approvals_submit_once(espn, monkeypatch):
    db, call, _listed = espn
    await linked_user(db, call)
    plan = await call('propose_fantasy_change', kind='lineup')
    real_send, overlapping = agent_tools.send, []

    def racing(*args):
        # A second key arrives while the first approval is about to submit.
        with pytest.raises(ToolError) as error:
            agent_tools.approve(db, db.user, 'lineup', plan['proposal_id'], 'approve-2', False)
        overlapping.append(str(error.value))
        return real_send(*args)
    monkeypatch.setattr(agent_tools, 'send', racing)
    done = await approve(call, 'lineup', plan['proposal_id'])
    assert done['status'] == 'ok'
    assert len(overlapping) == 1 and 'lineup approval is not confirmed' in overlapping[0]
    settled = await approve(call, 'lineup', plan['proposal_id'], key='approve-2')
    assert settled['status'] == 'set' and settled['confirmed_from'] == 'your ESPN lineup'
    assert [kind for kind, _swid in sends(db)] == ['lineup']


def test_retry_messages_never_suggest_a_new_key():
    for message in (UNCONFIRMED, UNSETTLED):
        assert 'same idempotency_key' in message and 'new key' not in message and 'new idempotency' not in message
