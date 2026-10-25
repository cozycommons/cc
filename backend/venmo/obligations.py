"""Context-neutral friend obligations, embedded atomically alongside a host ledger.

The host supplies suggestions and persists the returned records with its ledger in
one transaction. This module never computes balances or accesses a host's tables.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid5, NAMESPACE_URL


def reference_for(identifier):
    return 'CZ-' + identifier.replace('-', '')[:6].upper()


def reconcile(previous, suggestions, context, generation, timestamp):
    previous = deepcopy(previous)
    result = [item for item in previous if item['status'] == 'settled']
    matched = set()
    for suggestion in suggestions:
        fields = {key: suggestion[key] for key in ('from_member', 'to_member', 'amount_minor')}
        existing = next((item for item in previous if item['status'] == 'open' and all(item[k] == v for k, v in fields.items())), None)
        if existing:
            matched.add(existing['id'])
        identity = f"{context['kind']}:{context['id']}:{generation}:{fields}"
        identifier = str(uuid5(NAMESPACE_URL, identity))
        result.append(existing or {**fields, 'id': identifier, 'reference': reference_for(identifier),
                                  'context': context, 'status': 'open', 'created_at': timestamp,
                                  'settled_at': None, 'settled_by': None, 'nudged_at': None, 'cycle': 0})
    replaced = [item if item['status'] == 'replaced' else {**item, 'status': 'replaced', 'replaced_at': timestamp}
                for item in previous if item['status'] == 'replaced' or (item['status'] == 'open' and item['id'] not in matched)]
    result.extend(sorted(replaced, key=lambda item: item['replaced_at'], reverse=True)[:100])
    return result


def transition(obligation, action, actor, *, timestamp=None):
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    result = deepcopy(obligation)
    if actor not in (result['from_member'], result['to_member']):
        raise ValueError('Only the people on this payment can change it.')
    if result['status'] == 'replaced' and action != 'settle':
        raise ValueError('This payment changed.')
    if action == 'settle':
        result.update(status='settled', settled_at=timestamp, settled_by=actor)
    elif action == 'undo':
        result.update(status='open', settled_at=None, settled_by=None, cycle=result.get('cycle', 0) + (result['status'] == 'settled'))
    elif action == 'nudge':
        now = datetime.fromisoformat(timestamp)
        if actor != result['to_member'] or result['status'] != 'open':
            raise ValueError('Only the person owed can nudge an open payment.')
        if now - datetime.fromisoformat(result['created_at']) < timedelta(days=3):
            raise ValueError('Nudges are available after three days.')
        if result.get('nudged_at') and now - datetime.fromisoformat(result['nudged_at']) < timedelta(hours=48):
            raise ValueError('You can nudge again after 48 hours.')
        result['nudged_at'] = timestamp
    else:
        raise ValueError('Unknown obligation action.')
    return result
