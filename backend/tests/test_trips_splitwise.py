from copy import deepcopy

import pytest

from trips.ledger import LedgerError
from trips.splitwise import expense_date, from_printable, minor


@pytest.fixture
def captured():
    capture = {
        'source_url': 'https://secure.splitwise.com/api/v3.0/get_printable_summary?group_id=trip-1&date=',
        'captured_at': '2026-10-23T00:00:00Z', 'headings': ['Synthetic trip', 'Ari', 'Bo'],
        'tables': [
            [['Date', 'Description', 'Cost', 'Ari', 'Bo'],
             ['2026-10-20', 'Coffee', '$5.35', '$2.68', '-$2.68'],
             ['TOTAL BALANCE as of October 23, 2026', 'Ari gets back $2.68', 'Bo owes $2.68']],
            [['Date', 'Description', 'Cost', 'You paid', 'Your share', 'Balance'],
             ['2026-10-20', 'Coffee', '$5.35', '$5.35', '$2.67', 'you lent $2.68'],
             ['Total', '$5.35', '$2.67', 'you are owed $2.68']],
            [['Date', 'Description', 'Cost', 'You paid', 'Your share', 'Balance'],
             ['2026-10-20', 'Coffee', '$5.35', '$0.00', '$2.68', 'you borrowed $2.68'],
             ['Total', '$0.00', '$2.68', 'you owe $2.68']],
        ],
    }
    ids = {'group_id': 'trip-1', 'expenses': [{'source_id': 'source-1', 'description': 'Coffee'}]}
    return capture, ids, {'Ari': 'person-a', 'Bo': 'person-b'}


def convert(captured):
    return from_printable(*captured, 'USD')


def test_visible_summary_preserves_source_rounding_and_ids(captured):
    before = deepcopy(captured)
    result = convert(captured)
    assert result['expenses'][0]['id'] == 'source-1'
    assert result['expenses'][0]['shares'] == {'person-a': 267, 'person-b': 268}
    assert result['expected_balances'] == {'person-a': 268, 'person-b': -268}
    assert captured == before


@pytest.mark.parametrize('printed, display, expected', [
    ('2026-10-21', ['OCT', '20'], '2026-10-20'),
    ('2026-10-21', ['OCT', '21'], '2026-10-21'),
    ('2026-01-01', ['DEC', '31'], '2025-12-31'),
    ('2026-12-31', ['JAN', '1'], '2027-01-01'),
    ('2024-02-29', ['FEB', '29'], '2024-02-29'),
])
def test_source_group_dates_survive_utc_printable_day_changes(printed, display, expected):
    assert expense_date(printed, {'display': display}) == expected


def test_unrelated_display_date_is_not_guessed():
    with pytest.raises(LedgerError, match='display date'):
        expense_date('2026-10-21', {'display': ['FEB', '29']})


@pytest.mark.parametrize('value, expected', [('$1,234.56', 123456), ('-$0.01', -1), ('€2.00', 200), ('$0.00', 0)])
def test_source_money_is_exact(value, expected):
    assert minor(value) == expected


@pytest.mark.parametrize('value', ['1.234', '1e3', 'NaN', '$1,00.00', '1', '($2.00)', 'USD 2.00'])
def test_unsupported_source_money_is_rejected(value):
    with pytest.raises(LedgerError):
        minor(value)


@pytest.mark.parametrize('damage, expected', [
    (lambda c: c[0].update(source_url=c[0]['source_url'] + '2026-10'), 'All time'),
    (lambda c: c[1].update(group_id='another-trip'), 'different groups'),
    (lambda c: c[0]['tables'].pop(), 'incomplete'),
    (lambda c: c[2].pop('Bo'), 'every distinct person'),
    (lambda c: c[1]['expenses'].clear(), 'complete printable'),
    (lambda c: c[0]['tables'][1][-1].__setitem__(1, '$5.36'), 'totals and stated'),
    (lambda c: c[0]['tables'][0][-1].__setitem__(2, 'Bo owes $2.67'), 'Group and individual'),
    (lambda c: c[0]['tables'][2][1].__setitem__(1, 'Wrong expense'), 'expense rows disagree'),
    (lambda c: c[0]['tables'][0][1].__setitem__(3, '$2.67'), 'expense amounts disagree'),
])
def test_incomplete_or_inconsistent_capture_is_rejected(captured, damage, expected):
    damage(captured)
    with pytest.raises(LedgerError, match=expected):
        convert(captured)
