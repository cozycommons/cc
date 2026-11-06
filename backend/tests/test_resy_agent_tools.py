"""Resy on the shared connector: account link, previews with fees, terms checks and at-most-once writes."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from cc_mcp.registry import PROVIDERS
from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, build_server
from resy import agent_tools
from resy.agent_tools import LINK_STEP, UNCONFIRMED, UNSETTLED
from resy.resy_client import ResyAuthError, ResyError
from tests import resy_fakes
from tests.resy_fakes import VENUE_ID, day, slot_token
from tests.test_commons_agent_tools import Database, connect

TOOLS = {'find_resy_tables', 'list_resy_reservations', 'book_resy_table', 'cancel_resy_reservation'}


@pytest_asyncio.fixture
async def resy(monkeypatch):
    db = Database()
    resy_fakes.install(db, monkeypatch)
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE, EDIT_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    call, listed = connect(build_server(db, PROVIDERS))
    return db, call, listed


def enable(db):
    db.settings[(db.user.id, 'resy')] = {'user_id': db.user.id, 'project_id': 'resy', 'enabled': True}



async def linked_user(db, call):
    enable(db)
    row, _token = resy_fakes.add_account(db, owner=db.user.id)  # as the account page links it
    return row


def cards(db, row):
    return db.resy_cards[row['email']]


BOOK = {'venue_id': VENUE_ID, 'desired_time': '19:00', 'idempotency_key': 'book-1'}


async def preview(call, **arguments):
    return await call('book_resy_table', **{'date': day(), **BOOK, **arguments})


async def book(call, **arguments):
    terms_id = arguments.pop('terms_id', None) or (await preview(call, **arguments))['terms_id']
    return await call('book_resy_table', **{'date': day(), **BOOK, **arguments}, terms_id=terms_id, dry_run=False)


async def cancel(call, reservation_id, key='cancel-1'):
    terms = await call('cancel_resy_reservation', reservation_id=reservation_id, idempotency_key=key)
    return await call('cancel_resy_reservation', reservation_id=reservation_id, idempotency_key=key,
                      terms_id=terms['terms_id'], dry_run=False)


# Linking

@pytest.mark.asyncio
async def test_new_user_sees_resy_off_then_the_link_step(resy):
    db, call, listed = resy
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['resy']
    assert project['on_connector'] and project['enabled'] is False and project['linked'] is False
    assert {t['name']: t['access'] for t in project['tools']} == {
        'find_resy_tables': 'read', 'list_resy_reservations': 'read', 'book_resy_table': 'edit',
        'cancel_resy_reservation': 'edit'}
    assert not TOOLS & await listed()
    enabled = await call('enable_project', project_id='resy')
    assert enabled['linked'] is False and enabled['next_step'] == LINK_STEP
    assert 'cozycommons.dev/account#resy' in LINK_STEP and 'Do not ask for their Resy password or a ccr_ token' in LINK_STEP
    assert TOOLS <= await listed()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,arguments', [
    ('find_resy_tables', {'date': day(), 'venue_id': VENUE_ID}), ('list_resy_reservations', {}),
    ('book_resy_table', {'date': day(), **BOOK, 'terms_id': '0' * 16, 'dry_run': False}),
    ('cancel_resy_reservation', {'reservation_id': 1, 'idempotency_key': 'c', 'terms_id': '0' * 16,
                                 'dry_run': False})])
async def test_unlinked_user_gets_the_link_step(resy, tool, arguments):
    db, call, _ = resy
    enable(db)
    resy_fakes.add_account(db, owner=str(uuid4()))  # someone else's linked account
    with pytest.raises(ToolError, match='Link your Resy account first: Ask the user to connect Resy at https://cozycommons.dev/account#resy'):
        await call(tool, **arguments)
    assert not db.resy_logins and not db.resy_sends and not db.resy_receipts


@pytest.mark.asyncio
async def test_a_page_linked_account_turns_resy_on_and_no_token_tool_exists(resy):
    db, call, listed = resy
    row, token = resy_fakes.add_account(db, owner=db.user.id)  # as /account/linked-accounts links it
    project = {p['id']: p for p in (await call('list_projects'))['projects']}['resy']
    assert project['enabled'] and project['linked'] and project['status']['in_use']
    assert project['enabled_reason'] == 'default: you already use it'
    assert 'link_resy_account' not in await listed()
    with pytest.raises(ToolError, match='Unknown tool'):
        await call('link_resy_account', api_token=token)





# Reads

@pytest.mark.asyncio
async def test_find_tables_by_venue_or_query_with_fees_in_cents(resy):
    db, call, _ = resy
    other, _ = resy_fakes.add_account(db, owner=str(uuid4()))
    mine = await linked_user(db, call)
    found = await call('find_resy_tables', date=day(), venue_id=VENUE_ID)
    venue = found['venues'][0]
    assert venue['name'] == 'Synthetic Trattoria' and venue['venue_id'] == VENUE_ID
    assert venue['slots'][0] == {'slot_token': slot_token(day(), '19:00', 'Dining Room'), 'type': 'Dining Room',
                                 'time': '19:00', 'end': '21:00', 'deposit_cents': 2500,
                                 'cancellation_fee_cents': 5000}
    near = await call('find_resy_tables', date=day(), query='trattoria', time='21:30')
    assert [s['time'] for s in near['venues'][0]['slots']] == ['21:00', '21:00']
    assert db.resy_logins == [mine['email']] * 2 and other['email'] not in db.resy_logins
    with pytest.raises(ToolError, match='exactly one of query'):
        await call('find_resy_tables', date=day(), query='trattoria', venue_id=VENUE_ID)
    with pytest.raises(ToolError):
        await call('find_resy_tables', date='next friday', venue_id=VENUE_ID)


@pytest.mark.asyncio
async def test_list_reservations_shows_only_your_account_and_no_resy_tokens(resy):
    db, call, _ = resy
    other, _ = resy_fakes.add_account(db, owner=str(uuid4()))
    theirs = resy_fakes.add_reservation(db, other['email'])
    mine = resy_fakes.add_reservation(db, (await linked_user(db, call))['email'])
    listed = (await call('list_resy_reservations'))['reservations']
    assert [r['reservation_id'] for r in listed] == [mine['reservation_id']]
    assert str(theirs['reservation_id']) not in repr(listed) and 'rr://' not in repr(listed)


# Booking

@pytest.mark.asyncio
async def test_booking_preview_names_deposit_fee_policy_and_card_and_writes_nothing(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    result = await preview(call)
    terms = result['terms']
    assert result['dry_run'] is True and result['status'] == 'would_book'
    assert terms['deposit_cents'] == 2500 and terms['cancellation_fee_cents'] == 5000
    assert terms['cancellation_fee_after'] == db.resy_fees['cut_off']
    assert terms['cancellation_policy'] == resy_fakes.POLICY
    assert terms['payment_method'] == {'id': cards(db, row)[0]['id'], 'label': 'Visa ....4242'}
    summary = result['summary']
    for text in ('Deposit: USD 25.00 charged to Visa ....4242', 'Cancellation fee: USD 50.00',
                 f"if cancelled after {db.resy_fees['cut_off']}", 'Cancel at least 24 hours ahead', 'Synthetic Trattoria'):
        assert text in summary
    assert [m['label'] for m in result['payment_methods']] == ['Visa ....4242', 'Amex ....1005']
    assert not db.resy_sends and not db.resy_receipts
    free = await preview(call, desired_time=None, slot_token=slot_token(day(), '21:00', 'Bar'))
    assert free['terms']['deposit_cents'] == 0 and free['terms']['cancellation_fee_cents'] is None
    assert 'Deposit: none.' in free['summary'] and 'Cancellation fee: not stated by Resy' in free['summary']


@pytest.mark.asyncio
async def test_book_commit_replay_and_key_reuse(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    booked = await book(call)
    assert booked['status'] == 'booked' and booked['dry_run'] is False
    assert booked['summary'].startswith('Booked: Synthetic Trattoria') and 'USD 50.00' in booked['summary']
    assert db.resy_writes == [('book', row['email'])]
    reservation = db.resy_reservations[row['email']][0]
    assert booked['reservation_id'] == reservation['reservation_id']
    # The slot is now gone from Resy; a replay still returns the original result without sending.
    assert await call('book_resy_table', date=day(), **BOOK, terms_id=booked['terms_id'], dry_run=False) == booked
    assert len(db.resy_sends) == 1
    with pytest.raises(ToolError, match='already used for: Booked: Synthetic Trattoria'):
        await call('book_resy_table', date=day(), **{**BOOK, 'desired_time': '21:00'}, terms_id=booked['terms_id'],
                   dry_run=False)
    assert len(db.resy_sends) == 1


@pytest.mark.asyncio
async def test_book_commit_needs_the_previewed_terms(resy):
    db, call, _ = resy
    await linked_user(db, call)
    with pytest.raises(ToolError, match='Preview first with dry_run=true'):
        await call('book_resy_table', date=day(), **BOOK, dry_run=False)
    first = await preview(call)
    db.resy_fees['cancellation_fee'] = 75.0  # the venue raised its fee after the preview
    with pytest.raises(ToolError, match='terms changed since the preview, so nothing was sent') as error:
        await call('book_resy_table', date=day(), **BOOK, terms_id=first['terms_id'], dry_run=False)
    assert 'Cancellation fee: USD 75.00' in str(error.value)
    assert not db.resy_sends and not db.resy_receipts
    current = str(error.value).split("terms_id='")[1][:16]
    assert (await call('book_resy_table', date=day(), **BOOK, terms_id=current, dry_run=False))['status'] == 'booked'
    assert len(db.resy_sends) == 1


@pytest.mark.asyncio
async def test_two_slots_at_one_time_need_an_exact_slot_token(resy):
    db, call, _ = resy
    await linked_user(db, call)
    with pytest.raises(ToolError, match='2 slots at 21:00') as error:
        await preview(call, desired_time='21:00')
    assert slot_token(day(), '21:00', 'Bar') in str(error.value)
    with pytest.raises(ToolError, match='No slot at 18:00 on .* Available: 19:00, 21:00'):
        await preview(call, desired_time='18:00')
    with pytest.raises(ToolError, match='exactly one of slot_token'):
        await preview(call, slot_token=slot_token(day(), '19:00', 'Dining Room'))
    assert not db.resy_sends


@pytest.mark.asyncio
async def test_payment_method_is_one_of_your_own_cards(resy):
    db, call, _ = resy
    other, _ = resy_fakes.add_account(db, owner=str(uuid4()))
    row = await linked_user(db, call)
    chosen = await preview(call, payment_method_id=cards(db, row)[1]['id'])
    assert chosen['terms']['payment_method']['label'] == 'Amex ....1005'
    with pytest.raises(ToolError, match='is not on your Resy account'):
        await preview(call, payment_method_id=cards(db, other)[0]['id'])
    assert not db.resy_sends


@pytest.mark.asyncio
async def test_uncertain_booking_is_settled_from_reservations_never_booked_twice(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    terms_id = (await preview(call))['terms_id']
    db.resy_after_write = TimeoutError('read timed out')  # Resy booked it; the answer was lost
    with pytest.raises(ToolError, match='may have gone through. Call book_resy_table again with the same '
                                        'idempotency_key') as error:
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    assert 'new' not in str(error.value)
    assert db.resy_receipts[(db.user.id, 'book-1')]['result'] is None
    db.resy_after_write = None
    # A retry with other details may not abandon the unconfirmed key.
    with pytest.raises(ToolError, match='unconfirmed request with other details') as error:
        await call('book_resy_table', date=day(), **{**BOOK, 'desired_time': '21:00'}, terms_id=terms_id,
                   dry_run=False)
    assert 'new key' not in str(error.value)
    settled = await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    assert settled['status'] == 'booked' and settled['confirmed_from'] == 'your Resy reservations'
    assert settled['reservation_id'] == db.resy_reservations[row['email']][0]['reservation_id']
    assert db.resy_sends == [('book', row['email'])] and len(db.resy_reservations[row['email']]) == 1
    assert await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False) == settled


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [TimeoutError('timed out'), ResyError('Resy book -> 502', status=502),
                                     ResyAuthError('expired')])
async def test_unrecorded_booking_keeps_the_key_and_never_sends_again(resy, failure):
    # The request failed before Resy recorded it, but nothing can prove that: the key stays spent.
    db, call, _ = resy
    await linked_user(db, call)
    terms_id = (await preview(call))['terms_id']
    db.resy_lost_write = failure
    with pytest.raises(ToolError, match='may have gone through'):
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    db.resy_lost_write = None
    for _ in range(2):
        with pytest.raises(ToolError, match='reservations do not show a new reservation at Synthetic Trattoria') \
                as error:
            await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
        assert 'new key' not in str(error.value) and 'same idempotency_key' in str(error.value)
    assert len(db.resy_sends) == 1 and not db.resy_writes
    assert db.resy_receipts[(db.user.id, 'book-1')]['result'] is None


@pytest.mark.asyncio
async def test_lost_booking_never_settles_on_a_reservation_you_already_held(resy):
    # The user already holds this exact venue/date/time/party; the new POST never reached Resy.
    db, call, _ = resy
    row = await linked_user(db, call)
    held = resy_fakes.add_reservation(db, row['email'])
    terms_id = (await preview(call))['terms_id']
    db.resy_lost_write = TimeoutError('timed out')
    with pytest.raises(ToolError, match='may have gone through'):
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    db.resy_lost_write = None
    assert db.resy_receipts[(db.user.id, 'book-1')]['target']['held'] == [held['reservation_id']]
    with pytest.raises(ToolError, match='do not show a new reservation at Synthetic Trattoria') as error:
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    assert 'check the Resy app' in str(error.value) and 'new key' not in str(error.value)
    assert db.resy_receipts[(db.user.id, 'book-1')]['result'] is None and len(db.resy_sends) == 1


@pytest.mark.asyncio
async def test_concurrent_holder_of_the_key_never_sends(resy):
    # Another request reserved this key a moment ago and has not answered yet.
    db, call, _ = resy
    row = await linked_user(db, call)
    terms = await preview(call)
    fingerprint = {'action': 'book', 'account_id': row['id'], 'venue_id': VENUE_ID, 'date': day(),
                   'party_size': 2, 'slot_token': None, 'desired_time': '19:00', 'payment_method_id': None}
    db.resy_receipts[(db.user.id, 'book-1')] = {
        'user_id': db.user.id, 'idempotency_key': 'book-1', 'payload': fingerprint, 'result': None,
        'target': {'terms_id': terms['terms_id'], 'terms': terms['terms'], 'held': []}}
    with pytest.raises(ToolError, match='not confirmed'):
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms['terms_id'], dry_run=False)
    assert not db.resy_sends


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,message', [
    (ResyError('Resy find slots -> 503', status=503), r'Resy did not answer \(HTTP 503\).*nothing was booked'),
    (ResyAuthError('dead'), 'sign in to Resy again at https://cozycommons.dev/account#resy')])
async def test_read_failures_before_sending_name_the_fix_and_spend_no_key(resy, failure, message):
    db, call, _ = resy
    await linked_user(db, call)
    terms_id = (await preview(call))['terms_id']
    db.resy_failure = failure
    with pytest.raises(ToolError, match=message):
        await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False)
    assert not db.resy_receipts and not db.resy_sends
    db.resy_failure = None
    assert (await call('book_resy_table', date=day(), **BOOK, terms_id=terms_id, dry_run=False))['status'] == 'booked'


# Cancelling

@pytest.mark.asyncio
async def test_cancel_preview_names_the_fee_then_cancels_once(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    reservation = resy_fakes.add_reservation(db, row['email'])
    previewed = await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                           idempotency_key='cancel-1')
    assert previewed['status'] == 'would_cancel' and previewed['terms']['cancellation_fee_cents'] == 5000
    assert previewed['terms']['fee_applies'] is False
    assert 'Cancelling now costs nothing.' in previewed['summary']
    assert 'Cancellation fee: USD 50.00 if cancelled after' in previewed['summary']
    assert 'Cancel at least 24 hours ahead' in previewed['summary'] and not db.resy_sends
    done = await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                      idempotency_key='cancel-1', terms_id=previewed['terms_id'], dry_run=False)
    assert done['status'] == 'cancelled' and db.resy_writes == [('cancel', row['email'])]
    assert not db.resy_reservations[row['email']]
    assert await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                      idempotency_key='cancel-1', terms_id=previewed['terms_id'], dry_run=False) == done
    assert len(db.resy_sends) == 1


@pytest.mark.asyncio
async def test_cancel_after_the_deadline_shows_the_fee_and_refuses_stale_terms(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    reservation = resy_fakes.add_reservation(db, row['email'])
    before = await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                        idempotency_key='cancel-1')
    passed = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    reservation['cancellation']['fee']['date_cut_off'] = passed
    with pytest.raises(ToolError, match='terms changed since the preview') as error:
        await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                   idempotency_key='cancel-1', terms_id=before['terms_id'], dry_run=False)
    assert 'Cancelling now costs USD 50.00' in str(error.value)
    assert not db.resy_sends and not db.resy_receipts


@pytest.mark.asyncio
async def test_cancel_inside_the_deadline_margin_counts_the_fee_and_sends_nothing(resy, monkeypatch):
    # Previewed 2 minutes before the fee deadline; committed 30s before it, too close to promise no fee.
    db, call, _ = resy
    row = await linked_user(db, call)
    reservation = resy_fakes.add_reservation(db, row['email'])
    deadline = datetime.fromisoformat(reservation['cancellation']['fee']['date_cut_off'])
    clock = [deadline - timedelta(minutes=2)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]
    monkeypatch.setattr(agent_tools, 'datetime', Clock)
    before = await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                        idempotency_key='cancel-1')
    assert before['terms']['fee_applies'] is False
    clock[0] = deadline - timedelta(seconds=agent_tools.CANCEL_MARGIN_S // 2)
    with pytest.raises(ToolError, match='terms changed since the preview') as error:
        await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                   idempotency_key='cancel-1', terms_id=before['terms_id'], dry_run=False)
    assert 'Cancelling now costs USD 50.00' in str(error.value) and 'costs nothing' not in str(error.value)
    assert not db.resy_sends and not db.resy_receipts


@pytest.mark.asyncio
async def test_cancel_targets_only_your_own_cancellable_reservations(resy):
    db, call, _ = resy
    other, _ = resy_fakes.add_account(db, owner=str(uuid4()))
    theirs = resy_fakes.add_reservation(db, other['email'])
    row = await linked_user(db, call)
    locked = resy_fakes.add_reservation(db, row['email'], allowed=False)
    with pytest.raises(ToolError, match=f"No reservation {theirs['reservation_id']} in your Resy account"):
        await call('cancel_resy_reservation', reservation_id=theirs['reservation_id'], idempotency_key='c',
                   terms_id='0' * 16, dry_run=False)
    with pytest.raises(ToolError, match='does not allow cancelling .* contact the restaurant'):
        await call('cancel_resy_reservation', reservation_id=locked['reservation_id'], idempotency_key='c')
    assert not db.resy_sends and not db.resy_receipts and len(db.resy_reservations[other['email']]) == 1


@pytest.mark.asyncio
async def test_uncertain_cancel_settles_when_the_reservation_is_gone(resy):
    db, call, _ = resy
    row = await linked_user(db, call)
    reservation = resy_fakes.add_reservation(db, row['email'])
    db.resy_after_write = ResyError('Resy cancel -> 504', status=504)
    with pytest.raises(ToolError, match='Resy did not confirm the cancellation'):
        await cancel(call, reservation['reservation_id'])
    db.resy_after_write = None
    terms_id = db.resy_receipts[(db.user.id, 'cancel-1')]['target']['terms_id']
    settled = await call('cancel_resy_reservation', reservation_id=reservation['reservation_id'],
                         idempotency_key='cancel-1', terms_id=terms_id, dry_run=False)
    assert settled['status'] == 'cancelled' and settled['confirmed_from'] == 'your Resy reservations'
    assert len(db.resy_sends) == 1


def test_retry_messages_never_suggest_a_new_key():
    for text in (UNCONFIRMED, *UNSETTLED.values()):
        assert 'same idempotency_key' in text and 'new key' not in text and 'new idempotency' not in text
