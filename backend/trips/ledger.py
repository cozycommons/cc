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


def balances(data):
    result = {member['id']: 0 for member in data['members']}
    for expense in data['expenses']:
        result[expense['paid_by']] += expense['amount_minor']
        for member_id, amount in expense['shares'].items():
            result[member_id] -= amount
    for repayment in data['repayments']:
        result[repayment['from_member']] += repayment['amount_minor']
        result[repayment['to_member']] -= repayment['amount_minor']
    return result


def transfers(amounts):
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


def public_group(row):
    data = deepcopy(row['data'])
    for member in data['members']:
        member.pop('invite_hash', None)
    amounts = balances(data)
    return {**data, 'id': row['id'], 'owner_id': row['owner_id'],
            'revision': row['revision'], 'created_at': row['created_at'],
            'balances': amounts, 'transfers': transfers(amounts),
            'total_minor': sum(item['amount_minor'] for item in data['expenses'])}


def new_group(group_id, user_id, name, currency, display_name):
    return {'id': group_id, 'owner_id': user_id, 'member_user_ids': [user_id],
            'revision': 1, 'created_at': now(), 'updated_at': now(),
            'data': {'name': name, 'currency': currency,
                     'members': [{'id': str(uuid4()), 'name': display_name, 'user_id': user_id}],
                     'expenses': [], 'repayments': [], 'activity': []}}


def require_member(row, user_id):
    if not is_member(row, user_id):
        raise LedgerError('Trip not found or you are not a member.', 404)


def apply_command(row, user_id, command, payload):
    """Return a complete revision to save with compare-and-swap. Never mutate input."""
    require_member(row, user_id)
    if payload['revision'] != row['revision']:
        raise LedgerError('Someone changed this trip. Refresh, review the changes, and try again.', 409)
    result = deepcopy(row)
    data = result['data']
    members = {member['id']: member for member in data['members']}
    timestamp = now()
    invite_token = None

    if command in {'add_member', 'invite_member'}:
        if row['owner_id'] != user_id:
            raise LedgerError('Only the trip creator can manage invitations.', 403)
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
        invite_token = secrets.token_urlsafe(32)
        member['invite_hash'] = sha256(invite_token.encode()).hexdigest()
        summary = f"Invited {member['name']}"
    elif command in {'add_expense', 'edit_expense'}:
        if payload['paid_by'] not in members:
            raise LedgerError('Choose a payer on this trip.')
        participants = payload['participants']
        if not participants or len(set(participants)) != len(participants) or not set(participants) <= members.keys():
            raise LedgerError('Choose each participant once from this trip.')
        amount = payload['amount_minor']
        if payload['split_mode'] == 'equal':
            # Member order, rather than checkbox order, makes pennies deterministic.
            ordered = [key for key in members if key in participants]
            quotient, remainder = divmod(amount, len(ordered))
            shares = {key: quotient + int(index < remainder) for index, key in enumerate(ordered)}
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
        expense = {key: payload[key] for key in
                   ['id', 'description', 'amount_minor', 'paid_by', 'split_mode', 'date', 'category', 'notes']}
        expense.update(shares=shares, created_by=existing['created_by'] if existing else user_id,
                       created_at=existing['created_at'] if existing else timestamp,
                       updated_by=user_id, updated_at=timestamp)
        if existing:
            data['expenses'][data['expenses'].index(existing)] = expense
        else:
            data['expenses'].append(expense)
        summary = f"{'Updated' if existing else 'Added'} {expense['description']}"
    elif command == 'delete_expense':
        expense = next((e for e in data['expenses'] if e['id'] == payload['id']), None)
        if not expense:
            raise LedgerError('Expense not found.', 404)
        data['expenses'].remove(expense)
        summary = f"Deleted {expense['description']}"
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
    elif command == 'delete_repayment':
        repayment = next((p for p in data['repayments'] if p['id'] == payload['id']), None)
        if not repayment:
            raise LedgerError('Repayment not found.', 404)
        data['repayments'].remove(repayment)
        summary = 'Removed a repayment'
    else:
        raise LedgerError('Unknown trip command.')

    data['activity'] = ([{'id': str(uuid4()), 'user_id': user_id, 'summary': summary, 'at': timestamp}]
                        + data['activity'])[:100]
    result['revision'] += 1
    result['updated_at'] = timestamp
    return result, invite_token


def claim_invite(row, user_id, token):
    digest = sha256(token.encode()).hexdigest()
    member = next((m for m in row['data']['members']
                   if secrets.compare_digest(m.get('invite_hash', ''), digest)), None)
    if not member or member.get('user_id'):
        raise LedgerError('This invitation is invalid or has already been used.', 404)
    if is_member(row, user_id):
        raise LedgerError('You already have a place on this trip. Use another account to accept this invitation.', 409)
    result = deepcopy(row)
    target = next(m for m in result['data']['members'] if m['id'] == member['id'])
    target['user_id'] = user_id
    target.pop('invite_hash')
    result['member_user_ids'].append(user_id)
    result['revision'] += 1
    result['updated_at'] = now()
    result['data']['activity'] = ([{'id': str(uuid4()), 'user_id': user_id,
                                   'summary': f"{target['name']} joined the trip", 'at': now()}]
                                 + result['data']['activity'])[:100]
    return result
