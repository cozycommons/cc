"""Strict, previewable Trips tools on the shared OAuth connector."""
from datetime import date as Date
from difflib import get_close_matches
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from cc_mcp.server import EDIT_SCOPE, READ_SCOPE, ToolProvider
from venmo.links import transaction_link
from .ledger import LedgerError, apply_command, require_member
from .profiles import render_group
from .routes import Expense, Repayment, Input, Money, Share, Name
from .service import read_row

Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
MemberId = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class Payer(Input):
    member_id: MemberId
    amount_cents: Money


def status(client, user):
    count = (client.table('trips_groups').select('id', count='exact', head=True)
             .contains('member_user_ids', [user.id]).execute()).count
    return {'in_use': bool(count), 'trip_count': count,
            'next_step': 'Call get_trip_overview.' if count else 'Create a trip at https://cozycommons.dev/trips.'}


def trip_rows(client, user):
    return (client.table('trips_groups').select('*').contains('member_user_ids', [user.id])
            .order('updated_at', desc=True).execute().data)


def member_ids(row, requested):
    members = row['data']['members']
    by_id = {m['id']: m for m in members}
    for value in requested:
        if value not in by_id:
            names = {m['name']: m['id'] for m in members}
            matches = get_close_matches(value, list(names), n=3, cutoff=0.4)
            suggestions = [f'{name} (id {names[name]})' for name in matches]
            if not suggestions:
                suggestions = [f"{m['name']} (id {m['id']})" for m in members[:3]]
            raise ToolError(f"No member '{value}' on this trip; use an exact member id. "
                            + 'Did you mean ' + ', '.join(suggestions) + '?')


def overview(client, user, trip_id=None):
    if trip_id is None:
        return {'trips': [{'id': row['id'], 'name': row['data']['name'],
                           'dates': row['data'].get('dates'), 'member_count': len(row['data']['members'])}
                          for row in trip_rows(client, user)]}
    row = read_row(client, trip_id)
    require_member(row, user.id)
    group = render_group(client, row)
    members = {m['id']: m for m in group['members']}
    payments = []
    for payment in group['transfers']:
        sender, recipient = (members[payment[key]] for key in ('from_member', 'to_member'))
        amount = payment['amount_minor']
        # Venmo supports USD. Never offer a dollar link for a different currency.
        usd = group['currency'] == 'USD'
        payments.append({'from_member_id': sender['id'], 'to_member_id': recipient['id'], 'amount_cents': amount,
                         'pay_url': transaction_link(recipient['venmo_username'], amount, group['name'])
                         if usd and recipient.get('venmo_username') else None,
                         'request_url': transaction_link(sender['venmo_username'], amount, group['name'], action='charge')
                         if usd and sender.get('venmo_username') else None})
    return {'id': group['id'], 'name': group['name'], 'currency': group['currency'], 'revision': group['revision'],
            'members': [{'id': m['id'], 'name': m.get('display_name') or m['name'],
                         'venmo_username': m.get('venmo_username')} for m in group['members']],
            'balances_cents': group['balances'], 'settlement': group['settlement'], 'payments': payments}


def write(client, user, trip_id, kind, arguments, key, dry_run):
    """Apply the canonical ledger command, CAS once and retry one revision conflict.

    Receipt and ledger are committed in one SQL transaction. Preview never reserves a key.
    The request fingerprint excludes generated IDs, default dates and dry_run.
    """
    fingerprint = {'trip_id': str(trip_id), 'kind': kind, 'arguments': arguments}
    item_id = str(uuid4())
    default_date = Date.today().isoformat()
    for attempt in range(2):
        before = read_row(client, trip_id)
        require_member(before, user.id)
        if not dry_run:
            receipts = (client.table('trips_agent_receipts').select('payload,result')
                        .eq('user_id', user.id).eq('idempotency_key', key).execute().data)
            if receipts:
                if receipts[0]['payload'] != fingerprint:
                    raise ToolError('This idempotency_key was used with different details. Use a new key for a new write.')
                return receipts[0]['result']
        base = {'id': item_id, 'revision': before['revision'], 'date': default_date, 'notes': ''}
        if kind == 'add_expense':
            payers = arguments['payers']
            ids = [payer['member_id'] for payer in payers]
            participants = arguments['member_ids']
            member_ids(before, [*ids, *participants, *arguments['parts']])
            if len(set(ids)) != len(ids) or sum(p['amount_cents'] for p in payers) != arguments['total_cents']:
                raise ToolError('List each payer once; payer amounts must sum to total_cents.')
            mode = arguments['split_mode']
            if mode == 'even' and arguments['parts']:
                raise ToolError('Omit parts for an even split; use member_ids for participants.')
            payload = Expense(**{**base, 'description': arguments['description'], 'amount_minor': arguments['total_cents'],
                                 'paid_by': ids[0], 'payers': {p['member_id']: p['amount_cents'] for p in payers} if len(ids) > 1 else {},
                                 'participants': participants, 'split_mode': 'equal' if mode == 'even' else mode,
                                 'shares': arguments['parts'], 'date': arguments['date'] or default_date,
                                 'category': arguments['category']}).model_dump(mode='json')
        else:
            member_ids(before, [arguments['from_member_id'], arguments['to_member_id']])
            payload = Repayment(**{**base, 'from_member': arguments['from_member_id'],
                                   'to_member': arguments['to_member_id'], 'amount_minor': arguments['amount_cents']}).model_dump(mode='json')
        after, _ = apply_command(before, user.id, kind, payload)
        collection = 'expenses' if kind == 'add_expense' else 'repayments'
        item = next(item for item in after['data'][collection] if item['id'] == item_id)
        result = {'dry_run': dry_run, 'trip_id': str(trip_id), 'currency': before['data']['currency'],
                  'revision': after['revision'], 'item': item}
        if kind == 'add_expense':
            result['per_person_cents'] = item['shares']
        if dry_run:
            return result
        committed = client.rpc('trips_agent_commit', {'p_user_id': user.id, 'p_key': key,
            'p_payload': fingerprint, 'p_trip_id': str(trip_id), 'p_revision': before['revision'],
            'p_after': after, 'p_result': result}).execute().data
        if 'result' in committed:
            return committed['result']
        error = committed.get('error')
        if error == 'revision' and attempt == 0:
            continue
        messages = {'revision': 'Revision conflict after one retry. Read get_trip_overview, review changes and try again.',
                    'membership': 'Trip not found or you are not a member. Ask a trip member for an invitation.',
                    'idempotency': 'This idempotency_key was used with different details. Use a new key for a new write.'}
        raise ToolError(messages.get(error, 'Trip write failed. Read the trip before retrying.'))


def register_tools(mcp, context):
    async def invoke(scope, operation, *args):
        access = context.need_scope(scope)
        user = await context.signed_in_user(access)
        try:
            return await run_in_threadpool(operation, context.service_client, user, *args)
        except LedgerError as error:
            raise ToolError(str(error)) from error

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def get_trip_overview(trip_id: UUID | None = None) -> dict:
        """List your trips or read members, balances in cents, and settlement links.

        Settlement uses the existing exact fewest-payment solver up to 16 nonzero balances;
        larger trips use the existing deterministic greedy fallback. Venmo links require USD and handles.
        """
        return await invoke(READ_SCOPE, overview, trip_id)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False})
    async def add_expense(
        trip_id: UUID, description: Name, total_cents: Money,
        payers: Annotated[list[Payer], Field(min_length=1, max_length=30)],
        member_ids: Annotated[list[MemberId], Field(min_length=1, max_length=30)],
        idempotency_key: Key, split_mode: Literal['even', 'percent', 'exact'] = 'even',
        parts: dict[MemberId, Share] | None = None, date: Date | None = None,
        category: Literal['food', 'stay', 'transport', 'activities', 'other'] = 'other',
        dry_run: Annotated[bool, Field(strict=True)] = True,
    ) -> dict:
        """Preview first, then save an expense using exact member IDs and integer cents.

        Percent parts are basis points totaling 10000 (1250 = 12.5%); exact parts are cents.
        Parts must cover member_ids exactly. Even remainders go in trip member order;
        percent uses largest remainder, ties in trip member order. Same key and payload
        returns the original saved result; changed details need a new key. Date defaults to today.
        """
        arguments = {'description': description, 'total_cents': total_cents,
                     'payers': [p.model_dump() for p in payers], 'member_ids': member_ids,
                     'split_mode': split_mode, 'parts': parts or {},
                     'date': date.isoformat() if date else None, 'category': category}
        return await invoke(EDIT_SCOPE, write, trip_id, 'add_expense', arguments, idempotency_key, dry_run)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False})
    async def record_repayment(trip_id: UUID, from_member_id: MemberId, to_member_id: MemberId,
                               amount_cents: Money, idempotency_key: Key,
                               dry_run: Annotated[bool, Field(strict=True)] = True) -> dict:
        """Preview first, then record a repayment already made; this does not send money."""
        return await invoke(EDIT_SCOPE, write, trip_id, 'add_repayment',
                            {'from_member_id': from_member_id, 'to_member_id': to_member_id,
                             'amount_cents': amount_cents}, idempotency_key, dry_run)


provider = ToolProvider(
    'trips', register_tools,
    {'get_trip_overview': 'read', 'add_expense': 'edit', 'record_repayment': 'edit'},
    title='Cozy Trips', description='Shared trip expenses, balances and repayments.',
    url='https://cozycommons.dev/trips', status=status,
    legacy_scopes={'trips:read': 'read', 'trips:edit': 'edit'})
