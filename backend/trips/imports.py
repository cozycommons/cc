"""Validated, atomic snapshots of one Splitwise trip; no continuous sync."""
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .ledger import LedgerError, balances, now

SourceId = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_.:-]{1,80}$')]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Money = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]
Share = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Balance = Annotated[int, Field(strict=True, ge=-5_000_000_000_000, le=5_000_000_000_000)]


class SourceModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceMember(SourceModel):
    id: SourceId
    name: Name


class SourceExpense(SourceModel):
    id: SourceId
    description: Name
    amount_minor: Money
    paid_by: SourceId
    shares: Annotated[dict[SourceId, Share], Field(min_length=1, max_length=30)]
    date: date
    category: Literal['food', 'stay', 'transport', 'activities', 'other'] = 'other'
    notes: Annotated[str, StringConstraints(max_length=1000)] = ''


class SourceRepayment(SourceModel):
    id: SourceId
    from_member: SourceId
    to_member: SourceId
    amount_minor: Money
    date: date
    notes: Annotated[str, StringConstraints(max_length=1000)] = ''


class SplitwiseSnapshot(SourceModel):
    format: Literal['cozy-trips-splitwise-v1']
    group_id: SourceId
    name: Name
    currency: Literal['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'MXN']
    captured_at: datetime
    members: Annotated[list[SourceMember], Field(min_length=1, max_length=30)]
    expenses: Annotated[list[SourceExpense], Field(max_length=5000)]
    repayments: Annotated[list[SourceRepayment], Field(max_length=5000)] = Field(default_factory=list)
    expected_balances: Annotated[dict[SourceId, Balance], Field(min_length=1, max_length=30)]


class ImportTrip(SourceModel):
    snapshot: SplitwiseSnapshot
    own_member_id: SourceId


def prepare_import(snapshot, user_id, own_member_id):
    """Validate all relationships and reconcile before constructing a row to insert."""
    source = SplitwiseSnapshot.model_validate(snapshot).model_dump(mode='json')
    source_members = {m['id']: m for m in source['members']}
    if len(source_members) != len(source['members']):
        raise LedgerError('Source members must have distinct IDs.')
    if own_member_id not in source_members:
        raise LedgerError('Choose your person in the source trip.')
    if set(source['expected_balances']) != set(source_members):
        raise LedgerError('Source balances must include every person exactly once.')
    group_id = str(uuid5(NAMESPACE_URL, f"cozy-trips:splitwise:{user_id}:{source['group_id']}"))
    member_ids = {key: str(uuid5(NAMESPACE_URL, f'{group_id}:member:{key}')) for key in source_members}
    timestamp = now()
    members = [{'id': member_ids[m['id']], 'name': m['name'],
                'user_id': user_id if m['id'] == own_member_id else None,
                'source_id': m['id']} for m in source['members']]
    expenses, repayments = [], []
    for collection, items in [('expenses', source['expenses']), ('repayments', source['repayments'])]:
        if len({item['id'] for item in items}) != len(items):
            raise LedgerError(f'Source {collection} must have distinct IDs.')
        for item in items:
            common = {'id': str(uuid5(NAMESPACE_URL, f"{group_id}:{collection}:{item['id']}")),
                      'source_id': item['id'], 'date': item['date'], 'notes': item['notes'],
                      'created_by': user_id, 'created_at': timestamp}
            if collection == 'expenses':
                if item['paid_by'] not in source_members or not set(item['shares']) <= source_members.keys():
                    raise LedgerError('Source expense references a person outside the trip.')
                if sum(item['shares'].values()) != item['amount_minor']:
                    raise LedgerError(f"Shares do not equal the cost of {item['description']}.")
                expenses.append({**common, 'description': item['description'],
                    'amount_minor': item['amount_minor'], 'paid_by': member_ids[item['paid_by']],
                    'split_mode': 'exact', 'category': item['category'],
                    'shares': {member_ids[key]: value for key, value in item['shares'].items()},
                    'updated_by': user_id, 'updated_at': timestamp})
            else:
                sender, recipient = item['from_member'], item['to_member']
                if sender == recipient or sender not in source_members or recipient not in source_members:
                    raise LedgerError('Source repayment must reference two different trip members.')
                repayments.append({**common, 'from_member': member_ids[sender],
                    'to_member': member_ids[recipient], 'amount_minor': item['amount_minor']})
    data = {'name': source['name'], 'currency': source['currency'], 'members': members,
            'expenses': expenses, 'repayments': repayments, 'activity': [],
            'settle': {'started_at': None, 'started_by': None, 'ready': {}}}
    expected = {member_ids[key]: value for key, value in source['expected_balances'].items()}
    if balances(data) != expected:
        raise LedgerError('Import does not reconcile with every source balance. No trip was saved.')
    # Capture time is provenance, not content: taking the same snapshot again is idempotent.
    content = {key: value for key, value in source.items() if key != 'captured_at'}
    digest = sha256(json.dumps({'snapshot': content, 'own_member_id': own_member_id},
                              sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    data['source'] = {'provider': 'splitwise', 'group_id': source['group_id'],
                      'snapshot_sha256': digest, 'captured_at': source['captured_at'],
                      'original_balances': expected}
    data['activity'] = [{'id': str(uuid5(NAMESPACE_URL, f'{group_id}:import:{digest}')),
                         'user_id': user_id, 'summary': f'Imported {len(expenses)} expenses from Splitwise',
                         'at': timestamp}]
    row = {'id': group_id, 'owner_id': user_id, 'member_user_ids': [user_id], 'revision': 1,
           'created_at': timestamp, 'updated_at': timestamp, 'data': data}
    report = {'expense_count': len(expenses), 'repayment_count': len(repayments),
              'member_count': len(members), 'currency': source['currency'], 'reconciled': True,
              'source_group_id': source['group_id'], 'snapshot_sha256': digest}
    return row, report


def require_same_import(existing, proposed):
    if (existing['owner_id'] != proposed['owner_id'] or
        existing['data'].get('source', {}).get('snapshot_sha256') != proposed['data']['source']['snapshot_sha256']):
        raise LedgerError('This source trip was already imported with different contents or identity mapping. '
                          'Review the existing trip; it has not been overwritten.', 409)
