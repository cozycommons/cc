"""Integer money and the single-trip command boundary. No network or auth bypasses."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import secrets
from uuid import uuid4


class LedgerError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat()


def is_member(row, user_id):
    return user_id in row['member_user_ids']


def paid_amounts(expense):
    return expense.get('payers') or {expense['paid_by']: expense['amount_minor']}


def balances(data):
    result = {member['id']: 0 for member in data['members']}
    for expense in data['expenses']:
        for member_id, amount in paid_amounts(expense).items():
            result[member_id] += amount
        for member_id, amount in expense['shares'].items():
            result[member_id] -= amount
    for repayment in data['repayments']:
        result[repayment['from_member']] += repayment['amount_minor']
        result[repayment['to_member']] -= repayment['amount_minor']
    return result


# Bound the O(n * 2**n) exact search by nonzero balances, not trip size.
FEWEST_PAYMENTS_LIMIT = 16


def _greedy_transfers(amounts):
    debtors = [[key, -value] for key, value in amounts.items() if value < 0]
    creditors = [[key, value] for key, value in amounts.items() if value > 0]
    result = []
    for debtor in debtors:
        for creditor in creditors:
            amount = min(debtor[1], creditor[1])
            if amount:
                result.append({'from_member': debtor[0], 'to_member': creditor[0], 'amount_minor': amount})
                debtor[1] -= amount
                creditor[1] -= amount
    return result


def _settlement_mode(amounts):
    return 'fewest' if sum(value != 0 for value in amounts.values()) <= FEWEST_PAYMENTS_LIMIT else 'greedy'


def transfers(amounts):
    """Settle zero-sum integer nets, minimizing payments within the exact limit.

    A settlement's connected components are zero-sum groups. Maximizing their
    count gives the minimum n - groups payments. Each optimal group is
    indecomposable, so debtor-to-creditor greedy takes exactly k - 1 payments.
    """
    if _settlement_mode(amounts) == 'greedy':
        return _greedy_transfers(amounts)
    members = [(key, value) for key, value in amounts.items() if value]
    size = 1 << len(members)
    sums = [0] * size
    groups = [0] * size
    last = [0] * size
    values = {1 << index: value for index, (_, value) in enumerate(members)}
    for mask in range(1, size):
        bit = mask & -mask
        sums[mask] = sums[mask ^ bit] + values[bit]
        # Best ordering of this subset: earn a group whenever a prefix sums to
        # zero. Trying each final member is O(n * 2**n), not O(3**n) submasks.
        remaining = mask
        best = -1
        while remaining:
            bit = remaining & -remaining
            score = groups[mask ^ bit]
            if score > best:  # Ties choose the earliest member in input order.
                best = score
                last[mask] = bit
            remaining ^= bit
        groups[mask] = best + (sums[mask] == 0)

    result = []
    mask = size - 1
    group = 0
    while mask:
        bit = last[mask]
        group |= bit
        mask ^= bit
        if sums[mask] == 0:
            result.extend(_greedy_transfers({
                key: value for index, (key, value) in enumerate(members)
                if group & (1 << index)
            }))
            group = 0
    # Display debtor first, then creditor, in the ledger's member order.
    order = {key: index for index, key in enumerate(amounts)}
    result.sort(key=lambda item: (order[item['from_member']], order[item['to_member']]))
    return result


def weighted_shares(amount, weights):
    """Split minor units by weight. Leftover pennies go to the largest remainders, then member order."""
    total = sum(weights.values())
    shares = {key: amount * weight // total for key, weight in weights.items()}
    order = sorted(weights, key=lambda key: -(amount * weights[key] % total))  # Stable: ties keep member order.
    for key in order[:amount - sum(shares.values())]:
        shares[key] += 1
    return shares


def obligations_for(row):
    from venmo.obligations import reconcile
    return reconcile(row['data'].get('obligations', []), transfers(balances(row['data'])),
                     {'kind': 'trip', 'id': row['id']}, row['revision'], row['updated_at'])


def obligation_command(row, user_id, action, payload):
    from venmo.obligations import transition, reconcile
    items = obligations_for(row)
    item = next((item for item in items if item['id'] == payload['id']), None)
    if item is None:
        raise LedgerError('This payment changed. Refresh to see the latest amounts.', 409)
    cycle = item.get('cycle', 0)
    expected = payload.get('cycle', cycle)
    if expected != cycle:
        if action == 'undo' and item['status'] == 'open' and expected + 1 == cycle:
            return deepcopy(row), None
        raise LedgerError('This payment changed. Refresh before marking it again.', 409)
    actor = next((m['id'] for m in row['data']['members'] if m.get('user_id') == user_id), None)
    try:
        changed = transition(item, action, actor, timestamp=now())
    except ValueError as error:
        raise LedgerError(str(error), 422)
    if action == 'settle' and item['status'] == 'open':
        result, _ = apply_command(row, user_id, 'add_repayment', {
            'id': item['id'], 'from_member': item['from_member'], 'to_member': item['to_member'],
            'amount_minor': item['amount_minor'], 'date': now()[:10], 'notes': item['reference'], 'revision': row['revision']})
    elif action == 'undo' and item['status'] == 'settled':
        result, _ = apply_command(row, user_id, 'delete_repayment', {'id': item['id'], 'revision': row['revision']})
    elif action == 'nudge':
        result = deepcopy(row)
        result['revision'] += 1
        result['updated_at'] = now()
    else:
        return deepcopy(row), None  # Repeated taps and lost-response retries are idempotent.
    items = [changed if current['id'] == changed['id'] else current for current in items]
    result['data']['obligations'] = reconcile(items, transfers(balances(result['data'])),
        {'kind': 'trip', 'id': row['id']}, result['revision'], result['updated_at'])
    return result, None


def public_group(row):
    data = deepcopy(row['data'])
    data.pop('account_links', None)
    data['obligations'] = obligations_for(row)
    for member in data['members']:
        member.pop('invite_hash', None)
    amounts = balances(data)
    return {**data, 'id': row['id'], 'owner_id': row['owner_id'],
            'revision': row['revision'], 'created_at': row['created_at'],
            'balances': amounts, 'transfers': transfers(amounts), 'settlement': _settlement_mode(amounts),
            'total_minor': sum(item['amount_minor'] for item in data['expenses'])}


def new_group(group_id, user_id, name, currency, display_name):
    return {'id': group_id, 'owner_id': user_id, 'member_user_ids': [user_id],
            'revision': 1, 'created_at': now(), 'updated_at': now(),
            'data': {'name': name, 'currency': currency,
                     'members': [{'id': str(uuid4()), 'name': display_name, 'user_id': user_id}],
                     'expenses': [], 'repayments': [], 'activity': []}}


# Adding a record doesn't depend on what else is in the ledger, so it may land on a newer revision.
# 409 means "reload and review"; rules that a fresh revision can't satisfy answer 422 instead.
CREATES = {'add_expense', 'add_repayment', 'restore_expense'}


def involved(data, member_id):
    return (any(member_id in paid_amounts(e) or member_id in e['shares'] for e in data['expenses'])
            or any(member_id in (p['from_member'], p['to_member']) for p in data['repayments']))


def deleted_expense(data, expense_id):
    """The most recent deleted snapshot of an expense, kept in its activity entry so it can be restored."""
    return next((a['expense'] for a in data['activity'] if a.get('kind') == 'delete_expense'
                 and a.get('item_id') == expense_id and a.get('expense')), None)


def invite_digest(token):
    return sha256(token.encode()).hexdigest()


def new_invite(member):
    """Give a place a fresh one-use invitation; any older link for it stops working."""
    token = secrets.token_urlsafe(32)
    member['invite_hash'] = invite_digest(token)
    return token


def invite_slot(row, token):
    digest = invite_digest(token)
    return next((m for m in row['data']['members'] if secrets.compare_digest(m.get('invite_hash', ''), digest)), None)


def require_member(row, user_id):
    if not is_member(row, user_id):
        raise LedgerError('Trip not found or you are not a member.', 404)


def apply_command(row, user_id, command, payload):
    """Return a complete revision to save with compare-and-swap. Never mutate input."""
    require_member(row, user_id)
    if command not in CREATES and not command.startswith('obligation_') and payload['revision'] != row['revision']:
        raise LedgerError('Someone changed this trip. Refresh, review the changes, and try again.', 409)
    if command.startswith('obligation_'):
        return obligation_command(row, user_id, command.removeprefix('obligation_'), payload)
    result = deepcopy(row)
    data = result['data']
    data['obligations'] = obligations_for(row)
    members = {member['id']: member for member in data['members']}
    timestamp = now()
    invite_token = None
    entry = {}  # What the activity row points at, so it can show amounts and link back.
    owner_only = {'add_member', 'invite_member', 'rename_trip', 'rename_member', 'remove_member', 'link_member', 'unlink_member'}
    if command in owner_only and row['owner_id'] != user_id:
        raise LedgerError('Only the trip creator can manage the trip and its people.', 403)

    if command in {'add_member', 'invite_member'}:
        if command == 'add_member':
            if len(members) >= 30:
                raise LedgerError('A trip can have up to 30 people.')
            if any(m['name'].casefold() == payload['name'].casefold() for m in members.values()):
                raise LedgerError('Someone on this trip already has that name.')
            member = {'id': str(uuid4()), 'name': payload['name'], 'user_id': None}
            data['members'].append(member)
        else:
            member = members.get(payload['member_id'])
            if not member or member.get('user_id'):
                raise LedgerError('That person has already joined or is not on this trip.')
        invite_token = new_invite(member)
        summary = f"Invited {member['name']}"
    elif command in {'add_expense', 'edit_expense'}:
        if payload['paid_by'] not in members:
            raise LedgerError('Choose a payer on this trip.')
        payers = payload.get('payers') or {}
        if payers and (len(payers) < 2 or not set(payers) <= members.keys()
                       or any(value <= 0 for value in payers.values()) or sum(payers.values()) != payload['amount_minor']):
            raise LedgerError('When several people pay, give each payer an amount; together they must add up to the expense.')
        if payers:  # paid_by names the biggest payer (earliest member on ties) so one-payer views stay meaningful.
            payload = {**payload, 'paid_by': max((key for key in members if key in payers), key=lambda key: payers[key])}
        participants = payload['participants']
        if not participants or len(set(participants)) != len(participants) or not set(participants) <= members.keys():
            raise LedgerError('Choose each participant once from this trip.')
        amount = payload['amount_minor']
        # Member order, rather than checkbox order, makes pennies deterministic.
        ordered = [key for key in members if key in participants]
        weights = None
        if payload['split_mode'] == 'equal':
            quotient, remainder = divmod(amount, len(ordered))
            shares = {key: quotient + int(index < remainder) for index, key in enumerate(ordered)}
        elif payload['split_mode'] in {'shares', 'percent'}:
            # Percentages arrive as basis points (12.5% = 1250) so they stay whole-number weights.
            percent = payload['split_mode'] == 'percent'
            values = payload['shares']
            if (set(values) != set(participants) or any(not 1 <= w <= (10000 if percent else 1000) for w in values.values())
                    or (percent and sum(values.values()) != 10000)):
                raise LedgerError('Percentages must cover every selected person and add up to 100%.' if percent
                                  else 'Give each selected person between 1 and 1000 shares.')
            weights = {key: values[key] for key in ordered}
            shares = weighted_shares(amount, weights)
        else:
            shares = payload['shares']
            if set(shares) != set(participants) or sum(shares.values()) != amount:
                raise LedgerError('Exact shares must include every selected person and add up to the expense.')
        existing = next((e for e in data['expenses'] if e['id'] == payload['id']), None)
        if command == 'edit_expense' and not existing:
            raise LedgerError('Expense not found.', 404)
        if command == 'add_expense' and existing:
            raise LedgerError('This expense was already saved. Refresh to see it.', 409)
        if command == 'add_expense' and len(data['expenses']) >= 5000:
            raise LedgerError('This trip has reached its expense limit.')
        expense = {**(existing or {}), **{key: payload[key] for key in
                   ['id', 'description', 'amount_minor', 'paid_by', 'split_mode', 'date', 'category', 'notes']}}
        expense.pop('weights', None)
        expense.pop('payers', None)
        if weights:
            expense['weights'] = weights
        if payers:
            expense['payers'] = {key: payers[key] for key in members if key in payers}
        expense.update(shares=shares, created_by=existing['created_by'] if existing else user_id,
                       created_at=existing['created_at'] if existing else timestamp,
                       updated_by=user_id, updated_at=timestamp)
        if existing:
            data['expenses'][data['expenses'].index(existing)] = expense
        else:
            data['expenses'].append(expense)
        summary = f"{'Updated' if existing else 'Added'} {expense['description']}"
        entry = {'kind': command, 'item_id': expense['id'], 'amount_minor': amount}
    elif command == 'set_member_venmo':
        if row['owner_id'] != user_id:
            raise LedgerError('Only the trip creator can set Venmo for people who have not joined.', 403)
        member = members.get(payload['member_id'])
        if not member:
            raise LedgerError('That person is not on this trip.', 404)
        if member.get('user_id'):
            raise LedgerError('People who joined manage their own Venmo username.', 409)
        if payload['venmo_username']:
            member['venmo_username'] = payload['venmo_username']
            summary = f"Set Venmo for {member['name']}"
        else:
            member.pop('venmo_username', None)
            summary = f"Removed Venmo for {member['name']}"
    elif command in {'link_member', 'unlink_member'}:
        # One explicitly confirmed mapping at a time; callers must never derive it from names alone.
        member = members.get(payload['member_id'])
        if not member:
            raise LedgerError('That person is not on this trip.', 404)
        previous = member.get('user_id')
        if command == 'link_member':
            if previous:
                raise LedgerError('That person is already linked to an account.', 409)
            if payload['user_id'] in result['member_user_ids']:
                raise LedgerError('That account already has a place on this trip.', 409)
            member['user_id'] = payload['user_id']
            member.pop('invite_hash', None)  # An outstanding invitation can no longer claim this place.
            member.pop('venmo_username', None)  # Same as joining: the account owner manages their own username.
            result['member_user_ids'].append(payload['user_id'])
            summary = f"Linked {member['name']} to their account"
        else:
            if not previous:
                raise LedgerError('That person isn’t linked to an account.', 409)
            if previous != payload['user_id']:  # Never revoke an account the admin didn't review.
                raise LedgerError('That place is now linked to a different account. Review it again.', 409)
            if previous == row['owner_id']:
                raise LedgerError('The trip creator’s own place can’t be unlinked.', 422)
            # Their history stays on this place; a fresh invitation lets the right person claim it.
            member['user_id'] = None
            result['member_user_ids'].remove(previous)
            invite_token = new_invite(member)
            summary = f"Unlinked {member['name']} from their account"
        # Unlike the rolling activity feed, this record is never trimmed. The app's trip responses omit it, but members
        # can read their whole row through the Data API, so it holds only account IDs: no names or emails.
        data.setdefault('account_links', []).append({
            'action': command.removesuffix('_member'), 'member_id': member['id'], 'user_id': payload['user_id'],
            'by': user_id, 'at': timestamp})
    elif command == 'delete_expense':
        expense = next((e for e in data['expenses'] if e['id'] == payload['id']), None)
        if not expense:
            raise LedgerError('Expense not found.', 404)
        data['expenses'].remove(expense)
        summary = f"Deleted {expense['description']}"
        entry = {'kind': command, 'item_id': expense['id'], 'amount_minor': expense['amount_minor'], 'expense': expense}
    elif command == 'restore_expense':
        if any(e['id'] == payload['id'] for e in data['expenses']):
            raise LedgerError('This expense is already back on the trip.', 409)
        snapshot = deleted_expense(data, payload['id'])
        if not snapshot:
            raise LedgerError('This expense can no longer be restored.', 404)
        if not set(paid_amounts(snapshot)) <= members.keys() or not set(snapshot['shares']) <= members.keys():
            raise LedgerError('Someone on this expense has left the trip, so it can’t be restored.', 422)
        expense = {**snapshot, 'updated_by': user_id, 'updated_at': timestamp}
        data['expenses'].append(expense)
        summary = f"Restored {expense['description']}"
        entry = {'kind': command, 'item_id': expense['id'], 'amount_minor': expense['amount_minor']}
    elif command == 'add_repayment':
        sender, recipient = payload['from_member'], payload['to_member']
        if sender == recipient or sender not in members or recipient not in members:
            raise LedgerError('Choose two different people on this trip.')
        if any(p['id'] == payload['id'] for p in data['repayments']):
            raise LedgerError('This repayment was already saved. Refresh to see it.', 409)
        if len(data['repayments']) >= 5000:
            raise LedgerError('This trip has reached its repayment limit.')
        data['repayments'].append({key: payload[key] for key in
                                  ['id', 'from_member', 'to_member', 'amount_minor', 'date', 'notes']} |
                                 {'created_at': timestamp, 'created_by': user_id})
        summary = f"Recorded repayment from {members[sender]['name']} to {members[recipient]['name']}"
        entry = {'kind': command, 'item_id': payload['id'], 'amount_minor': payload['amount_minor']}
    elif command == 'delete_repayment':
        repayment = next((p for p in data['repayments'] if p['id'] == payload['id']), None)
        if not repayment:
            raise LedgerError('Repayment not found.', 404)
        linked = next((o for o in data.get('obligations', []) if o['id'] == repayment['id']), None)
        if linked and user_id not in {members.get(linked[party], {}).get('user_id') for party in ('from_member', 'to_member')}:
            raise LedgerError('Only the people on this payment can undo it.', 403)
        data['repayments'].remove(repayment)
        for obligation in data.get('obligations', []):
            if obligation['id'] == repayment['id']:
                obligation.update(status='open', settled_at=None, settled_by=None, cycle=obligation.get('cycle', 0) + 1)
        summary = (f"Removed repayment from {members[repayment['from_member']]['name']} "
                   f"to {members[repayment['to_member']]['name']}")
        entry = {'kind': command, 'item_id': repayment['id'], 'amount_minor': repayment['amount_minor']}
    elif command == 'rename_trip':
        summary = f"Renamed the trip to {payload['name']}"
        data['name'] = payload['name']
    elif command in {'rename_member', 'remove_member'}:
        member = members.get(payload['member_id'])
        if not member:
            raise LedgerError('That person is not on this trip.', 404)
        if command == 'rename_member':
            if member.get('user_id'):
                raise LedgerError('People who joined use the name on their own profile.', 422)
            if any(m['name'].casefold() == payload['name'].casefold() for m in members.values() if m is not member):
                raise LedgerError('Someone on this trip already has that name.')
            summary = f"Renamed {member['name']} to {payload['name']}"
            member['name'] = payload['name']
        else:
            if member.get('user_id') == row['owner_id']:
                raise LedgerError('The trip creator can’t be removed.', 422)
            if involved(data, member['id']):
                raise LedgerError(f"{member['name']} is on expenses or payments. Remove them from those first.", 422)
            data['members'].remove(member)
            if member.get('user_id'):
                result['member_user_ids'].remove(member['user_id'])
            summary = f"Removed {member['name']} from the trip"
    else:
        raise LedgerError('Unknown trip command.')

    data['activity'] = ([{'id': str(uuid4()), 'user_id': user_id, 'summary': summary, 'at': timestamp, **entry}]
                        + data['activity'])[:100]
    result['revision'] += 1
    result['updated_at'] = timestamp
    data['obligations'] = obligations_for(result)
    return result, invite_token


def claim_invite(row, user_id, token):
    member = invite_slot(row, token)
    if not member or member.get('user_id'):
        raise LedgerError('This invitation is invalid or has already been used.', 404)
    if is_member(row, user_id):
        raise LedgerError('You already have a place on this trip. Use another account to accept this invitation.', 409)
    result = deepcopy(row)
    target = next(m for m in result['data']['members'] if m['id'] == member['id'])
    target['user_id'] = user_id
    target.pop('invite_hash')
    target.pop('venmo_username', None)  # The account owner manages their own username after joining.
    result['member_user_ids'].append(user_id)
    result['revision'] += 1
    result['updated_at'] = now()
    result['data']['activity'] = ([{'id': str(uuid4()), 'user_id': user_id,
                                   'summary': f"{target['name']} joined the trip", 'at': now()}]
                                 + result['data']['activity'])[:100]
    return result
