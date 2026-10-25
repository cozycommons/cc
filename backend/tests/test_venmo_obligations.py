from copy import deepcopy
from datetime import datetime, timezone, timedelta
import pytest
from tests.test_trips import trip, expense
from trips.ledger import apply_command, balances, obligations_for, LedgerError
from venmo.obligations import transition


def owing_trip():
    row, _ = trip()
    row['data']['members'][1]['user_id'] = 'alex'
    row['member_user_ids'].append('alex')
    row, _ = apply_command(row, 'matt', 'add_expense', expense(row))
    return row


def test_derivation_settle_undo_and_both_party_idempotence():
    row = owing_trip()
    original = balances(row['data'])
    item = next(o for o in obligations_for(row) if o['from_member'] == row['data']['members'][1]['id'])
    payload = {'id': item['id'], 'amount_minor': item['amount_minor']}
    settled, _ = apply_command(row, 'alex', 'obligation_settle', payload)
    assert len(settled['data']['repayments']) == 1
    assert next(o for o in obligations_for(settled) if o['id'] == item['id'])['status'] == 'settled'
    again, _ = apply_command(settled, 'matt', 'obligation_settle', payload)
    assert again == settled
    undone, _ = apply_command(settled, 'matt', 'obligation_undo', payload)
    assert balances(undone['data']) == original
    assert not undone['data']['repayments']
    assert next(o for o in obligations_for(undone) if o['id'] == item['id'])['status'] == 'open'
    again, _ = apply_command(undone, 'alex', 'obligation_undo', payload)
    assert again == undone


def test_stale_suggestion_never_settles_wrong_amount_and_third_party_cannot_settle():
    row = owing_trip()
    item = obligations_for(row)[0]
    changed, _ = apply_command(row, 'matt', 'add_expense', expense(row, amount=6000))
    with pytest.raises(LedgerError):
        apply_command(changed, 'matt', 'obligation_settle', {'id': item['id'], 'amount_minor': item['amount_minor']})
    other = next(o for o in obligations_for(row) if o['from_member'] != row['data']['members'][1]['id'])
    with pytest.raises(LedgerError):
        apply_command(row, 'alex', 'obligation_settle', {'id': other['id']})


def test_nudge_age_and_48h_rate_limit():
    row = owing_trip()
    item = obligations_for(row)[0]
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        transition(item, 'nudge', item['to_member'])
    item['created_at'] = (now - timedelta(days=4)).isoformat()
    nudged = transition(item, 'nudge', item['to_member'], timestamp=now.isoformat())
    with pytest.raises(ValueError):
        transition(nudged, 'nudge', item['to_member'], timestamp=(now + timedelta(hours=47)).isoformat())
    assert transition(nudged, 'nudge', item['to_member'], timestamp=(now + timedelta(hours=48)).isoformat())['nudged_at']
    with pytest.raises(ValueError):
        transition(item, 'nudge', item['from_member'])


def test_delayed_settle_retry_after_undo_cannot_settle_again():
    row = owing_trip()
    item = obligations_for(row)[0]
    payload = {'id': item['id'], 'cycle': 0, 'amount_minor': item['amount_minor']}
    settled, _ = apply_command(row, 'matt', 'obligation_settle', payload)
    undone, _ = apply_command(settled, 'matt', 'obligation_undo', payload)
    with pytest.raises(LedgerError):
        apply_command(undone, 'matt', 'obligation_settle', payload)
    assert apply_command(undone, 'matt', 'obligation_undo', payload)[0] == undone


def test_third_member_cannot_delete_obligation_repayment_through_legacy_command():
    row = owing_trip()
    row['data']['members'][2]['user_id'] = 'jamie'
    row['member_user_ids'].append('jamie')
    item = next(o for o in obligations_for(row) if o['from_member'] == row['data']['members'][1]['id'])
    settled, _ = apply_command(row, 'alex', 'obligation_settle', {'id': item['id'], 'amount_minor': item['amount_minor']})
    before = deepcopy(settled)
    with pytest.raises(LedgerError) as error:
        apply_command(settled, 'jamie', 'delete_repayment', {'id': item['id'], 'revision': settled['revision']})
    assert error.value.status == 403
    assert settled == before
    for party in ['alex', 'matt']:
        undone, _ = apply_command(settled, party, 'delete_repayment', {'id': item['id'], 'revision': settled['revision']})
        assert not undone['data']['repayments']
        assert balances(undone['data']) == balances(row['data'])


@pytest.mark.parametrize('amount', [None, 1, 5678])
def test_settle_rejects_missing_or_mismatched_amount(amount):
    row = owing_trip()
    item = obligations_for(row)[0]
    before = deepcopy(row)
    with pytest.raises(LedgerError) as error:
        apply_command(row, 'matt', 'obligation_settle', {'id': item['id'], 'cycle': 0, 'amount_minor': amount})
    assert error.value.status == 409
    assert row == before and not row['data']['repayments']
