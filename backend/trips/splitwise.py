"""Convert tables captured from Splitwise's visible all-time printable summary.

The browser capture uses rendered headings/rows, not private application state.
Expense and member IDs come from the visible group list. This adapter rejects
ambiguous, incomplete, or unsupported data instead of guessing financial shares.
"""
import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from .imports import SplitwiseSnapshot, prepare_import
from .ledger import LedgerError


def minor(text):
    match = re.fullmatch(r'(-?)(?:[$€£])?((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})', str(text).strip())
    if not match:
        raise LedgerError(f'Unsupported source money format: {text!r}.')
    value = int(Decimal(match[2].replace(',', '')) * 100)
    return -value if match[1] else value


def stated_balance(text):
    text = ' '.join(text.split())
    if text.endswith('settled up') or text.endswith('no balance'):
        return 0
    for phrase, sign in [('gets back ', 1), ('are owed ', 1), ('owes ', -1), ('you owe ', -1)]:
        if phrase in text:
            return sign * minor(text.rsplit(phrase, 1)[1])
    raise LedgerError('The source does not contain an explicit ending balance for every person.')


def expense_date(printed, source_row):
    """Retain the group UI's local date when the printable view uses a UTC day."""
    printed_date = date.fromisoformat(printed)
    display = source_row.get('display', [])
    if len(display) < 2:
        return printed
    months = {name: index for index, name in enumerate(
        ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
    month = months.get(display[0].strip().upper())
    candidates = []
    if month:
        for year in [printed_date.year - 1, printed_date.year, printed_date.year + 1]:
            try:
                candidates.append(date(year, month, int(display[1])))
            except ValueError:
                continue
    matches = [candidate for candidate in candidates if abs((candidate - printed_date).days) <= 1]
    if len(matches) != 1:
        raise LedgerError('The group display date and printable expense date disagree.')
    return matches[0].isoformat()


def from_printable(capture, expense_ids, member_ids, currency):
    url = urlparse(capture['source_url'])
    parameters = parse_qs(url.query, keep_blank_values=True)
    if (url.scheme != 'https' or url.netloc != 'secure.splitwise.com'
        or url.path != '/api/v3.0/get_printable_summary'
        or parameters.get('date') != ['']):
        raise LedgerError('Capture the All time printable summary, including the full history.')
    group_id = parameters.get('group_id', [''])[0]
    if group_id != str(expense_ids['group_id']):
        raise LedgerError('The printable summary and expense IDs belong to different groups.')
    headings, tables = capture['headings'], capture['tables']
    if len(headings) < 2 or len(tables) != len(headings) or len(tables[0]) < 2:
        raise LedgerError('The printable summary is incomplete.')
    names, summary = headings[1:], tables[0]
    if len(set(names)) != len(names) or set(member_ids) != set(names):
        raise LedgerError('Provide an explicit source ID for every distinct person in the summary.')
    if summary[0][:3] != ['Date', 'Description', 'Cost'] or len(summary[0]) != len(names) + 3:
        raise LedgerError('Unsupported printable summary columns.')
    source_rows = summary[1:-1]
    if len(expense_ids['expenses']) != len(source_rows):
        raise LedgerError('Expense IDs do not cover the complete printable summary.')
    by_description = {}
    for item in expense_ids['expenses']:
        if item['description'] in by_description:
            raise LedgerError('Repeated descriptions require an explicit canonical snapshot with source IDs.')
        by_description[item['description']] = item
    if len(by_description) != len(source_rows) or len({row[1] for row in source_rows}) != len(source_rows):
        raise LedgerError('Repeated descriptions require an explicit canonical snapshot with source IDs.')
    expected = {}
    for index, name in enumerate(names):
        table = tables[index + 1]
        if (table[0] != ['Date', 'Description', 'Cost', 'You paid', 'Your share', 'Balance']
            or len(table) != len(summary) or len(table[-1]) != 4 or table[-1][0] != 'Total'):
            raise LedgerError('A person’s printable history is incomplete or unsupported.')
        expected[member_ids[name]] = stated_balance(table[-1][3])
        if minor(table[-1][1]) - minor(table[-1][2]) != expected[member_ids[name]]:
            raise LedgerError('Source totals and stated ending balance disagree.')
    if len(summary[-1]) != len(names) + 1 or not summary[-1][0].startswith('TOTAL BALANCE'):
        raise LedgerError('The group ending balance row is missing.')
    if any(stated_balance(summary[-1][index + 1]) != expected[member_ids[name]]
           for index, name in enumerate(names)):
        raise LedgerError('Group and individual ending balances disagree.')
    expenses = []
    for row_index, row in enumerate(source_rows, start=1):
        if len(row) != len(names) + 3 or row[1] not in by_description:
            raise LedgerError('An expense is missing from the captured group list.')
        paid, shares = {}, {}
        for person_index, name in enumerate(names):
            detail = tables[person_index + 1][row_index]
            if len(detail) != 6 or detail[:3] != row[:3]:
                raise LedgerError('Individual and group expense rows disagree.')
            payer_amount, share = minor(detail[3]), minor(detail[4])
            if payer_amount < 0 or share < 0 or payer_amount - share != minor(row[person_index + 3]):
                raise LedgerError('Source expense amounts disagree or contain an unsupported refund.')
            if payer_amount:
                paid[member_ids[name]] = payer_amount
            if share:
                shares[member_ids[name]] = share
        cost = minor(row[2])
        if len(paid) != 1 or sum(paid.values()) != cost:
            raise LedgerError('Multiple payers or payment rows need an explicit supported snapshot; nothing was imported.')
        source_row = by_description[row[1]]
        expenses.append({'id': source_row['source_id'], 'description': row[1],
                         'amount_minor': cost, 'paid_by': next(iter(paid)), 'shares': shares,
                         'date': expense_date(row[0], source_row)})
    snapshot = SplitwiseSnapshot.model_validate({
        'format': 'cozy-trips-splitwise-v1', 'group_id': group_id, 'name': headings[0],
        'currency': currency, 'captured_at': capture['captured_at'],
        'members': [{'id': member_ids[name], 'name': name} for name in names],
        'expenses': expenses, 'repayments': [], 'expected_balances': expected,
    })
    # Verify aggregate accounting as well as each displayed row before writing a file.
    prepare_import(snapshot, 'conversion-validation', snapshot.members[0].id)
    return snapshot.model_dump(mode='json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--expense-ids', type=Path, required=True)
    parser.add_argument('--member-ids', type=Path, required=True)
    parser.add_argument('--currency', choices=['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'MXN'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    snapshot = from_printable(json.loads(args.capture.read_text()),
        json.loads(args.expense_ids.read_text()), json.loads(args.member_ids.read_text()), args.currency)
    args.output.write_text(json.dumps(snapshot, indent=2) + '\n')
    print(f"Validated {len(snapshot['expenses'])} expenses and {len(snapshot['members'])} balances; saved {args.output}.")


if __name__ == '__main__':
    main()
