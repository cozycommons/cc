"""Resy tools on the shared OAuth connector (/mcp).

The Resy account is resolved from the signed-in Commons user, never from a
pasted token: the user links it once with link_resy_account. The legacy
token-per-call server at /resy/mcp and the /resy routes are unchanged.

Bookings and cancellations are real and can charge deposits and cancellation
fees. Each is previewed first (dry_run defaults to true) and the preview names
every fee, deposit, policy line and the masked card. A commit must present the
preview's terms_id; when the slot, fees or policy changed since, nothing is sent
and the new terms come back for another confirmation.
"""
from datetime import date as Date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import hashlib
import json
import logging
import time
from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, AccountLink, ToolProvider
from . import accounts
from .accounts import AccountError
from .logic import _hhmm, _slim_venue, list_payment_methods, list_reservations
from .resy_client import ResyAuthError, ResyError
from .routes import _coords_for

logger = logging.getLogger(__name__)

ONBOARD_URL = 'https://api.cozycommons.dev/resy/onboard'
DOCS_URL = 'https://github.com/cozycommons/cc/blob/main/docs/mcp/README.md#resy'
LINK_STEP = (f'Call link_resy_account(api_token) once with your existing ccr_ Resy token. No token yet? '
             f'Onboard with your Resy login at POST {ONBOARD_URL} (see {DOCS_URL}), then link the token it returns.')
RELINK_STEP = (f'Resy rejected the stored login. Onboard again at POST {ONBOARD_URL} with your current Resy '
               'password, then call link_resy_account with the new token.')
RECEIPTS = 'resy_agent_receipts'
MAX_VENUES = 10
NEAR_MINUTES = 60
# A cancel sent this close to the fee deadline may reach Resy after it, so it is
# treated as fee-applying. 60s covers the receipt write and Resy's round trip.
CANCEL_MARGIN_S = 60

# A receipt is written just before the request to Resy and never released, so a
# key whose outcome was not recorded can only be settled by reading Resy.
UNCONFIRMED = ('Resy did not confirm the {action}, so it may have gone through. Call {tool} again with the same '
               'idempotency_key and arguments; it checks your Resy reservations and never sends it twice.')
UNSETTLED = {
    'book': ('A booking with this idempotency_key is not confirmed: your Resy reservations do not show a new '
             'reservation at {where}. The earlier attempt may still be running or may have failed. Call '
             'book_resy_table again with the same idempotency_key and arguments in a minute; it never books twice. '
             'If the reservation never appears, ask the user to check the Resy app before booking anything else.'),
    'cancel': ('A cancellation with this idempotency_key is not confirmed: your Resy reservations still show '
               '{where}. The earlier attempt may still be running or may have failed. Call '
               'cancel_resy_reservation again with the same idempotency_key and arguments in a minute; it never '
               'cancels twice. If it stays, ask the user to check the Resy app.'),
}

# Same limit as /resy/onboard: 10 attempts per Commons user per hour.
_LINK_ATTEMPTS: dict[str, list[float]] = {}
_LINK_LIMIT = 10
_LINK_WINDOW_S = 3600

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Clock = Annotated[str, StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Id = Annotated[int, Field(strict=True, ge=1)]
PartySize = Annotated[int, Field(strict=True, ge=1, le=20)]
SlotToken = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
TermsId = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{16}$')]
DryRun = Annotated[bool, Field(strict=True)]


def linked(client, user):
    return accounts.linked_account_summary(client, user.id)


def status(client, user):
    account = linked(client, user)
    return {'in_use': account is not None,
            'next_step': 'Call find_resy_tables(date, query or venue_id).' if account else LINK_STEP}


def resy_call(operation, *args):
    """Run Resy reads (never a booking or cancellation request) with errors that name the fix."""
    try:
        return operation(*args)
    except ResyAuthError as error:
        raise ToolError(RELINK_STEP) from error
    except ResyError as error:
        detail = f' (HTTP {error.status})' if error.status else ''
        raise ToolError(f'Resy did not answer{detail}. Retry in a moment; nothing was booked or cancelled.') from error
    except ValueError as error:
        raise ToolError(f'{error}. Check the inputs and retry.') from error


def resy_client(client, user):
    try:
        account = accounts.get_account_by_owner(client, user.id)
    except AccountError as error:
        if str(error) == 'no linked account':
            raise ToolError(f'Link your Resy account first: {LINK_STEP}') from error
        logger.warning('Linked Resy credentials unavailable')
        raise ToolError('Could not read your linked Resy login. Retry in a moment; nothing changed.') from error
    return account, resy_call(accounts.make_client_for_account, client, account)


def cents(amount) -> int | None:
    """Resy's dollar amounts as integer cents; None when Resy states none."""
    if amount is None or isinstance(amount, bool):
        return None
    try:
        return int((Decimal(str(amount)) * 100).quantize(Decimal(1), ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def first(*values):
    return next((value for value in values if value is not None), None)


def money(amount, currency):
    return f'{currency} {amount // 100}.{amount % 100:02d}'


def policy_lines(value) -> list[str]:
    lines = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [line.strip()[:500] for line in lines if isinstance(line, str) and line.strip()][:10]


def minutes(clock):
    try:
        hours, mins = str(clock).split(':')[:2]
        return int(hours) * 60 + int(mins)
    except ValueError:
        return None


def slot_view(slot):
    config, when, payment = slot.get('config') or {}, slot.get('date') or {}, slot.get('payment') or {}
    return {'slot_token': config.get('token'), 'type': config.get('type'), 'time': _hhmm(when.get('start')),
            'end': _hhmm(when.get('end')), 'deposit_cents': cents(payment.get('deposit_fee')),
            'cancellation_fee_cents': cents(payment.get('cancellation_fee'))}


def slots_near(slots, near):
    views = [slot_view(slot) for slot in slots if isinstance(slot, dict)]
    if near is None:
        return views
    want = minutes(near)
    return [view for view in views
            if minutes(view['time']) is not None and abs(minutes(view['time']) - want) <= NEAR_MINUTES]


def find(client, user, day, party_size, query, venue_id, location, near):
    if (query is None) == (venue_id is None):
        raise ToolError('Pass exactly one of query (a restaurant name or cuisine) or venue_id.')
    _account, resy = resy_client(client, user)
    if venue_id is not None:
        slots = resy_call(resy.find_slots, venue_id, day, party_size)
        venue = resy_call(resy.get_venue, venue_id) or {}
        place = venue.get('location') or {}
        venues = [{'venue_id': venue_id, 'name': venue.get('name'), 'neighborhood': place.get('neighborhood'),
                   'city': place.get('locality'), 'slots': slots_near(slots, near)}]
    else:
        lat, lng = _coords_for(location, None, None)
        entries = [entry for entry in resy_call(resy.search, query, lat, lng, day, party_size)
                   if isinstance(entry, dict)][:MAX_VENUES]
        venues = [{**_slim_venue(entry, include_slots=False), 'slots': slots_near(entry.get('slots') or [], near)}
                  for entry in entries]
    return {'date': day, 'party_size': party_size, 'venues': venues,
            'note': 'Slot fees are Resy listings. book_resy_table with dry_run=true shows the exact terms.'}


def reservations(client, user, scope):
    _account, resy = resy_client(client, user)
    rows = resy_call(list_reservations, resy, scope)
    return {'scope': scope, 'reservations': [{k: v for k, v in row.items() if k != 'resy_token'} for row in rows]}


def digest(terms):
    return hashlib.sha256(json.dumps(terms, sort_keys=True).encode()).hexdigest()[:16]


def pick_card(methods, payment_method_id):
    if not methods:
        raise ToolError('No payment method on your Resy account. Add one at resy.com/account, then preview again.')
    if payment_method_id is None:
        return next((m for m in methods if m['is_default']), methods[0])
    card = next((m for m in methods if m['id'] == payment_method_id), None)
    if card is None:
        raise ToolError(f'Payment method {payment_method_id} is not on your Resy account. Omit payment_method_id '
                        'to use your default card, or pick an id from the preview’s payment_methods.')
    return card


def booking_terms(resy, venue_id, day, party_size, slot_token, desired_time, payment_method_id):
    """Read what a booking would agree to. Reads only: nothing is booked here."""
    slots = [slot for slot in resy.find_slots(venue_id, day, party_size) if isinstance(slot, dict)]
    if slot_token:
        matches = [slot for slot in slots if slot_view(slot)['slot_token'] == slot_token]
        if not matches:
            raise ToolError(f'That slot_token is not offered at venue {venue_id} on {day} for {party_size}. '
                            'Call find_resy_tables for current slots.')
    else:
        matches = [slot for slot in slots if slot_view(slot)['time'] == desired_time and slot_view(slot)['slot_token']]
        if not matches:
            times = ', '.join(sorted({v['time'] for v in map(slot_view, slots) if v['time']})) or 'none'
            raise ToolError(f'No slot at {desired_time} on {day} for {party_size}. Available: {times}.')
        if len(matches) > 1:
            options = '; '.join(f"{v['type'] or 'slot'}: slot_token={v['slot_token']}" for v in map(slot_view, matches))
            raise ToolError(f'{len(matches)} slots at {desired_time}: {options}. Ask the user which one, then '
                            'pass its slot_token.')
    slot = matches[0]
    view = slot_view(slot)
    details = resy.get_book_details(view['slot_token'], day, party_size)
    book_token = (details.get('book_token') or {}).get('value')
    if not book_token:
        raise ToolError('Resy did not offer that slot for booking. Call find_resy_tables for current slots.')
    payment, cancellation = details.get('payment') or {}, details.get('cancellation') or {}
    fee = cancellation.get('fee') or {}
    methods = list_payment_methods(resy)
    card = pick_card(methods, payment_method_id)
    terms = {
        'venue_id': venue_id, 'venue_name': (details.get('venue') or {}).get('name'), 'date': day,
        'time': view['time'], 'party_size': party_size, 'slot_type': view['type'], 'slot_token': view['slot_token'],
        'currency': (details.get('locale') or {}).get('currency') or 'USD',
        'payment_type': (payment.get('config') or {}).get('type'),
        'deposit_cents': first(cents((payment.get('amounts') or {}).get('total')), view['deposit_cents']),
        'cancellation_fee_cents': first(cents(fee.get('amount')), view['cancellation_fee_cents']),
        'cancellation_fee_after': fee.get('date_cut_off') or (slot.get('payment') or {}).get('time_cancel_cut_off'),
        'cancellation_policy': policy_lines((cancellation.get('display') or {}).get('policy')),
        'payment_method': {'id': card['id'], 'label': card['label']},
    }
    return terms, book_token, [{'id': m['id'], 'label': m['label'], 'is_default': m['is_default']} for m in methods]


def fee_lines(terms, card=None):
    currency, fee = terms['currency'], terms['cancellation_fee_cents']
    charged = f' to {card}' if card else ''
    if fee is None:
        line = 'Cancellation fee: not stated by Resy; read the policy.'
    elif fee == 0:
        line = 'Cancellation fee: none.'
    else:
        after = f" if cancelled after {terms['cancellation_fee_after']}" if terms['cancellation_fee_after'] else ''
        line = f'Cancellation fee: {money(fee, currency)}{charged}{after}.'
    policy = ' '.join(terms['cancellation_policy'])
    return [line] + ([f'Policy: {policy}'] if policy else [])


def where(terms):
    venue = terms['venue_name'] or f"venue {terms['venue_id']}"
    return f"{venue} on {terms['date']} at {terms['time']} for {terms['party_size']}"


def booking_summary(terms):
    card, deposit = terms['payment_method']['label'], terms['deposit_cents']
    kind = f" ({terms['slot_type']})" if terms['slot_type'] else ''
    if deposit is None:
        charge = 'Deposit: not stated by Resy.'
    elif deposit == 0:
        charge = 'Deposit: none.'
    else:
        charge = f"Deposit: {money(deposit, terms['currency'])} charged to {card} when booking."
    return ' '.join([f'{where(terms)}{kind}.', charge, *fee_lines(terms, card), f'Card on file: {card}.'])


def fee_applies(fee, after):
    if fee is None:
        return None
    if fee == 0:
        return False
    try:
        cutoff = datetime.fromisoformat(str(after))
    except ValueError:
        return True  # A fee without a readable deadline may apply now.
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return (cutoff - datetime.now(timezone.utc)).total_seconds() <= CANCEL_MARGIN_S


def cancelled(reservation):
    return bool((reservation.get('status') or {}).get('cancelled'))


def own_reservation(resy, reservation_id):
    """The caller's own active reservation with this id, from their Resy account only."""
    for item in resy.get_reservations():
        reservation = item.get('reservation') or {}
        if str(reservation.get('reservation_id')) == str(reservation_id) and not cancelled(reservation):
            return reservation, item.get('venue') or {}
    return None, None


def cancel_terms(resy, reservation_id):
    """Read what cancelling would cost. Reads only: nothing is cancelled here.

    A commit calls this right before its receipt and POST, so a deadline that falls
    within CANCEL_MARGIN_S flips fee_applies and the terms_id instead of letting a
    "costs nothing" cancel land after the deadline.
    """
    reservation, venue = own_reservation(resy, reservation_id)
    if reservation is None or not reservation.get('resy_token'):
        raise ToolError(f'No reservation {reservation_id} in your Resy account. Call list_resy_reservations '
                        'for your reservation ids.')
    rules = reservation.get('cancellation') or {}
    if rules.get('allowed') is not True:
        raise ToolError(f'Resy does not allow cancelling reservation {reservation_id} online. Ask the user to '
                        'contact the restaurant.')
    day = str(reservation.get('day') or '')
    if day and day < Date.today().isoformat():
        raise ToolError(f'Reservation {reservation_id} is in the past and cannot be cancelled.')
    fee = rules.get('fee') or {}
    amount = cents(fee.get('amount'))
    after = fee.get('date_cut_off') or rules.get('date_refund_cut_off')
    terms = {
        'reservation_id': reservation_id, 'venue_id': (reservation.get('venue') or {}).get('id'),
        'venue_name': venue.get('name'), 'date': day, 'time': _hhmm(reservation.get('time_slot')),
        'party_size': reservation.get('num_seats'), 'currency': (reservation.get('locale') or {}).get('currency') or 'USD',
        'cancellation_fee_cents': amount, 'cancellation_fee_after': after, 'fee_applies': fee_applies(amount, after),
        'cancellation_policy': policy_lines(reservation.get('cancellation_policy')
                                            or (rules.get('display') or {}).get('policy')),
    }
    return terms, reservation['resy_token']


def cancel_summary(terms):
    if terms['fee_applies']:
        charge = f"Cancelling now costs {money(terms['cancellation_fee_cents'], terms['currency'])}."
    elif terms['fee_applies'] is None:
        charge = 'Resy states no cancellation fee for this reservation; read the policy.'
    else:
        charge = 'Cancelling now costs nothing.'
    return ' '.join([f'Cancel reservation {terms["reservation_id"]}: {where(terms)}.', charge, *fee_lines(terms)])


def receipt(client, user, key):
    rows = (client.table(RECEIPTS).select('payload,target,result')
            .eq('user_id', user.id).eq('idempotency_key', key).execute().data)
    return rows[0] if rows else None


def record(client, user, key, result):
    (client.table(RECEIPTS).update({'result': result})
     .eq('user_id', user.id).eq('idempotency_key', key).is_('result', 'null').execute())


def same_slot(resy, terms):
    """Upcoming reservations of the user's at the booked venue, date, time and party size."""
    return [row for row in list_reservations(resy, 'upcoming')
            if str(row['venue_id']) == str(terms['venue_id']) and row['day'] == terms['date']
            and row['time'] == terms['time'] and row['party_size'] == terms['party_size']]


def settle(client, user, resy, key, found):
    """Settle a key whose Resy outcome was not recorded, by reading the user's reservations.

    The request that wrote the receipt may still be running or may have reached Resy
    before failing; nothing tells those apart, so this never sends anything.
    """
    action, terms = found['payload']['action'], found['target']['terms']
    try:
        if action == 'book':
            # A reservation the user already held at this slot is not this booking.
            held = {str(held_id) for held_id in found['target']['held']}
            match = next((row for row in same_slot(resy, terms) if str(row['reservation_id']) not in held), None)
            done = match is not None
        else:
            match, _venue = own_reservation(resy, terms['reservation_id'])
            done = match is None
    except ResyAuthError as error:
        raise ToolError(RELINK_STEP) from error
    except (ResyError, ValueError) as error:
        raise ToolError(UNSETTLED[action].format(where=where(terms))) from error
    if not done:
        raise ToolError(UNSETTLED[action].format(where=where(terms)))
    if action == 'book':
        result = {'dry_run': False, 'status': 'booked', 'reservation_id': match['reservation_id'],
                  'terms_id': found['target']['terms_id'], 'terms': terms,
                  'summary': 'Booked: ' + booking_summary(terms), 'confirmed_from': 'your Resy reservations'}
    else:
        result = {'dry_run': False, 'status': 'cancelled', 'reservation_id': terms['reservation_id'],
                  'terms_id': found['target']['terms_id'], 'terms': terms,
                  'summary': 'Cancelled: ' + cancel_summary(terms), 'confirmed_from': 'your Resy reservations'}
    record(client, user, key, result)
    return result


def replay(client, user, resy, key, found, fingerprint):
    if found['payload'] != fingerprint:
        if found['result'] is None:
            raise ToolError('This idempotency_key belongs to an earlier, unconfirmed request with other details. '
                            'Repeat that request with its original arguments and the same key to settle it, '
                            'before booking or cancelling anything else.')
        raise ToolError('This idempotency_key was already used for: ' + found['result']['summary']
                        + ' A different booking or cancellation needs its own key.')
    if found['result'] is not None:
        return found['result']
    return settle(client, user, resy, key, found)


def commit(client, user, resy, key, fingerprint, terms, terms_id, send, tool, summarize, held=()):
    """Send one confirmed write to Resy at most once per key: (Resy's answer, None) or (None, a replay).

    The receipt is written immediately before the request and is never released:
    once Resy may have the request, only settle() can finish the key. held lists
    the reservation ids a booking's settle() must not mistake for its own.
    """
    current = digest(terms)
    if terms_id != current:
        raise ToolError(f'The terms changed since the preview, so nothing was sent. New terms: {summarize(terms)} '
                        f"Show these to the user; if they agree, call {tool} again with dry_run=false, the same "
                        f"idempotency_key and terms_id='{current}'.")
    reserved = (client.table(RECEIPTS).upsert(
        {'user_id': user.id, 'idempotency_key': key, 'payload': fingerprint,
         'target': {'terms_id': current, 'terms': terms, 'held': list(held)}},
        on_conflict='user_id,idempotency_key', ignore_duplicates=True).execute().data)
    if not reserved:
        return None, replay(client, user, resy, key, receipt(client, user, key), fingerprint)
    try:
        return send(), None
    except Exception as error:
        logger.warning('Resy %s unconfirmed: %s', fingerprint['action'], type(error).__name__)
        action = 'booking' if fingerprint['action'] == 'book' else 'cancellation'
        raise ToolError(UNCONFIRMED.format(action=action, tool=tool)) from error


def need_terms_id(terms_id, dry_run):
    if not dry_run and terms_id is None:
        raise ToolError('Preview first with dry_run=true, show the user its summary, then commit with the '
                        'preview’s terms_id.')


def book(client, user, venue_id, day, party_size, slot_token, desired_time, payment_method_id, key, terms_id,
         dry_run):
    need_terms_id(terms_id, dry_run)
    if (slot_token is None) == (desired_time is None):
        raise ToolError('Pass exactly one of slot_token (from find_resy_tables) or desired_time (HH:MM).')
    account, resy = resy_client(client, user)
    fingerprint = {'action': 'book', 'account_id': account['id'], 'venue_id': venue_id, 'date': day,
                   'party_size': party_size, 'slot_token': slot_token, 'desired_time': desired_time,
                   'payment_method_id': payment_method_id}
    if not dry_run and (found := receipt(client, user, key)):
        return replay(client, user, resy, key, found, fingerprint)
    terms, book_token, methods = resy_call(booking_terms, resy, venue_id, day, party_size, slot_token,
                                           desired_time, payment_method_id)
    if dry_run:
        return {'dry_run': True, 'status': 'would_book', 'terms_id': digest(terms), 'terms': terms,
                'summary': booking_summary(terms), 'payment_methods': methods,
                'next_step': 'Show the user the summary, including every fee and the card. If they confirm, call '
                             'book_resy_table again with the same arguments, dry_run=false and this terms_id.'}
    held = [row['reservation_id'] for row in resy_call(same_slot, resy, terms)]
    booked, replayed = commit(client, user, resy, key, fingerprint, terms, terms_id,
                              lambda: resy.book(book_token, terms['payment_method']['id']), 'book_resy_table',
                              booking_summary, held)
    if replayed:
        return replayed
    result = {'dry_run': False, 'status': 'booked', 'reservation_id': booked.get('reservation_id'),
              'terms_id': terms_id, 'terms': terms, 'summary': 'Booked: ' + booking_summary(terms)}
    record(client, user, key, result)
    return result


def cancel(client, user, reservation_id, key, terms_id, dry_run):
    need_terms_id(terms_id, dry_run)
    account, resy = resy_client(client, user)
    fingerprint = {'action': 'cancel', 'account_id': account['id'], 'reservation_id': reservation_id}
    if not dry_run and (found := receipt(client, user, key)):
        return replay(client, user, resy, key, found, fingerprint)
    terms, resy_token = resy_call(cancel_terms, resy, reservation_id)
    if dry_run:
        return {'dry_run': True, 'status': 'would_cancel', 'terms_id': digest(terms), 'terms': terms,
                'summary': cancel_summary(terms),
                'next_step': 'Show the user the summary, including any fee. If they confirm, call '
                             'cancel_resy_reservation again with the same arguments, dry_run=false and this terms_id.'}
    _answer, replayed = commit(client, user, resy, key, fingerprint, terms, terms_id,
                               lambda: resy.cancel(resy_token), 'cancel_resy_reservation', cancel_summary)
    if replayed:
        return replayed
    result = {'dry_run': False, 'status': 'cancelled', 'reservation_id': reservation_id, 'terms_id': terms_id,
              'terms': terms, 'summary': 'Cancelled: ' + cancel_summary(terms)}
    record(client, user, key, result)
    return result


def rate_check(user_id):
    now = time.time()
    attempts = [t for t in _LINK_ATTEMPTS.get(user_id, []) if now - t < _LINK_WINDOW_S]
    if len(attempts) >= _LINK_LIMIT:
        raise ToolError('Too many link attempts. Try again in an hour.')
    attempts.append(now)
    _LINK_ATTEMPTS[user_id] = attempts


def link(client, user, api_token):
    rate_check(str(user.id))
    previous = linked(client, user)
    try:
        outcome, account = accounts.link_account_to_owner(client, api_token, user.id)
    except AccountError as error:
        raise ToolError('No Resy account matches that token. Use the ccr_ token from your Resy onboarding '
                        f'exactly as shown, or onboard again at POST {ONBOARD_URL}.') from error
    if outcome == 'other_owner':
        raise ToolError('This Resy account is linked to another Commons user. Sign in as that user, '
                        f'or onboard your own Resy login at POST {ONBOARD_URL}.')
    if outcome not in {'linked', 'already_linked'}:
        raise ToolError('Could not link the account. Retry in a moment; nothing changed.')
    result = {'linked': True, 'status': outcome, 'account': {'id': account['id'], 'label': account['label']},
              'next_step': 'Call find_resy_tables(date, query or venue_id) or list_resy_reservations.'}
    if outcome == 'linked' and previous and previous['id'] != account['id']:
        result['replaced_account'] = {'id': previous['id'], 'label': previous['label']}
    return result


def register_tools(mcp, context):
    async def invoke(scope, operation, *args):
        access = context.need_scope(scope)
        user = await context.signed_in_user(access)
        try:
            return await run_in_threadpool(operation, context.service_client, user, *args)
        except ToolError:
            raise
        except Exception as error:
            logger.warning('Resy connector call failed: %s', type(error).__name__)
            raise ToolError('The Resy request failed. Retry in a moment with the same arguments.') from error

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def find_resy_tables(date: Date, party_size: PartySize = 2, query: Text | None = None,
                               venue_id: Id | None = None, location: Text = 'New York',
                               time: Clock | None = None) -> dict:
        """Find Resy restaurants and their open tables for a date, with listed fees in integer cents.

        Pass query (a name or cuisine, searched near location) or venue_id (one venue).
        time (24-hour HH:MM) keeps slots within an hour of it. Each slot has a
        slot_token for book_resy_table.
        """
        return await invoke(READ_SCOPE, find, date.isoformat(), party_size, query, venue_id, location, time)

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': True})
    async def list_resy_reservations(scope: Literal['upcoming', 'past', 'all'] = 'upcoming') -> dict:
        """Your Resy reservations, with the reservation_id that cancel_resy_reservation takes."""
        return await invoke(READ_SCOPE, reservations, scope)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': True})
    async def book_resy_table(venue_id: Id, date: Date, idempotency_key: Key, party_size: PartySize = 2,
                              slot_token: SlotToken | None = None, desired_time: Clock | None = None,
                              payment_method_id: Id | None = None, terms_id: TermsId | None = None,
                              dry_run: DryRun = True) -> dict:
        """Preview, then book a real Resy table. Bookings can charge deposits and cancellation fees.

        Pick the slot by slot_token (from find_resy_tables) or desired_time. The preview
        (dry_run=true, the default) returns a summary naming the deposit, cancellation
        fee, policy and masked card, and a terms_id. Show the user the summary; after
        they confirm, call again with the same arguments, dry_run=false and terms_id.
        If the terms changed, nothing is booked and the new terms come back. After an
        error, retry with the same idempotency_key: it never books twice.
        """
        return await invoke(EDIT_SCOPE, book, venue_id, date.isoformat(), party_size, slot_token, desired_time,
                            payment_method_id, idempotency_key, terms_id, dry_run)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': True,
                           'openWorldHint': True})
    async def cancel_resy_reservation(reservation_id: Id, idempotency_key: Key, terms_id: TermsId | None = None,
                                      dry_run: DryRun = True) -> dict:
        """Preview, then cancel one of your own Resy reservations. Cancelling can charge a fee.

        The preview (dry_run=true, the default) names any cancellation fee, whether it
        applies now, and the policy, plus a terms_id. Show the user the summary; after
        they confirm, call again with dry_run=false and terms_id. After an error, retry
        with the same idempotency_key: it never cancels twice.
        """
        return await invoke(EDIT_SCOPE, cancel, reservation_id, idempotency_key, terms_id, dry_run)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def link_resy_account(api_token: str) -> dict:
        """Link your Resy account to your Commons sign-in once, using its existing ccr_ token.

        The token proves ownership; it is checked against its stored hash and never
        stored or returned. Afterwards the Resy tools need no token. Linking a different
        account of yours replaces the earlier link; an account linked to another Commons
        user is refused.
        """
        return await invoke(EDIT_SCOPE, link, api_token)


provider = ToolProvider(
    'resy', register_tools,
    {'find_resy_tables': 'read', 'list_resy_reservations': 'read', 'book_resy_table': 'edit',
     'cancel_resy_reservation': 'edit', 'link_resy_account': 'edit'},
    title='Resy', description='Find, book and cancel Resy restaurant reservations.',
    url=DOCS_URL, status=status,
    link=AccountLink(LINK_STEP, linked=linked, tool='link_resy_account', url=ONBOARD_URL))
