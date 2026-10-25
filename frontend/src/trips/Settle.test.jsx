import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { BalancesPanel } from './Settle.jsx';

afterEach(cleanup);

it.each(['fewest', 'greedy', undefined])('describes only the guarantee for %s settlement', (settlement) => {
  const group = { id: 't', currency: 'USD', settlement, expenses: [], repayments: [],
    members: [{ id: 'debtor', name: 'Sam' }, { id: 'creditor', name: 'Alex' }],
    balances: { debtor: -500, creditor: 500 },
    transfers: [{ from_member: 'debtor', to_member: 'creditor', amount_minor: 500 }] };
  render(<BalancesPanel group={group} onRecord={() => {}} />);
  const note = settlement === 'fewest'
    ? 'The fewest payments to square everyone.'
    : 'These square everyone with the least money changing hands.';
  expect(screen.getByText(note)).toBeInTheDocument();
  if (settlement !== 'fewest') expect(screen.queryByText(/fewest payments/)).not.toBeInTheDocument();
});

// Matt covered dinner for Jamie; Alex covered kayaks for Matt. Simplified, Jamie pays Alex and Matt is square.
it('labels person-by-person debts as before simplifying when the plan replaces them', () => {
  const members = [{ id: 'matt', user_id: 'u-matt', name: 'Matt' }, { id: 'alex', name: 'Alex' }, { id: 'jamie', name: 'Jamie' }];
  const group = { id: 't', currency: 'USD', settlement: 'fewest', members, repayments: [],
    expenses: [{ id: 'e1', paid_by: 'matt', amount_minor: 1000, shares: { jamie: 1000 } },
      { id: 'e2', paid_by: 'alex', amount_minor: 1000, shares: { matt: 1000 } }],
    balances: { matt: 0, alex: 1000, jamie: -1000 },
    transfers: [{ from_member: 'jamie', to_member: 'alex', amount_minor: 1000 }] };
  render(<BalancesPanel group={group} me={members[0]} onRecord={() => {}} />);
  fireEvent.click(screen.getByText('How your balance adds up'));
  expect(screen.getByRole('heading', { name: 'Before simplifying' })).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('You’re square: the payments above already cover all of these');
  expect(screen.getByText('You owe $10.00')).toBeInTheDocument();
});

it('keeps the plain person-by-person heading when nothing was simplified', () => {
  const members = [{ id: 'matt', user_id: 'u-matt', name: 'Matt' }, { id: 'alex', name: 'Alex' }];
  const group = { id: 't', currency: 'USD', settlement: 'fewest', members, repayments: [],
    expenses: [{ id: 'e1', paid_by: 'alex', amount_minor: 1000, shares: { matt: 1000 } }],
    balances: { matt: -1000, alex: 1000 }, transfers: [{ from_member: 'matt', to_member: 'alex', amount_minor: 1000 }] };
  render(<BalancesPanel group={group} me={members[0]} onRecord={() => {}} onVenmo={() => {}} />);
  fireEvent.click(screen.getByText('How your balance adds up'));
  expect(screen.getByRole('heading', { name: 'Person by person' })).toBeInTheDocument();
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
});

it('shows readiness, close-out provenance and creator Start now instead of payments', () => {
  const members = [{ id: 'me', user_id: 'u-me', name: 'Matt' }, { id: 'a', user_id: 'u-a', name: 'Alex' }];
  const group = { id: 'g', owner_id: 'u-me', currency: 'USD', members, expenses: [], repayments: [], balances: { me: -1234, a: 1234 }, transfers: [{ from_member: 'me', to_member: 'a', amount_minor: 1234 }], settle: { started: false, ready: { a: { by: 'me' } }, waiting: ['me'] } };
  render(<BalancesPanel group={group} me={members[0]} />);
  expect(screen.getByText('You owe so far')).toBeInTheDocument();
  expect(screen.getByText("Opens when everyone's done adding.")).toBeInTheDocument();
  expect(screen.getByText('Closed out by Matt')).toBeInTheDocument();
  expect(screen.getByText('Waiting on Matt')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Done adding' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start now' })).toBeInTheDocument();
  expect(screen.queryByText('Pay')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Record a payment' })).toBeInTheDocument();
});

it('shows Updated and up to three late changes with an Activity link', () => {
  const members = [{ id: 'me', user_id: 'u-me', name: 'Matt' }, { id: 'a', name: 'Alex' }];
  const transfer = { from_member: 'me', to_member: 'a', amount_minor: 100 };
  const group = { id: 'g', currency: 'USD', members, expenses: [], repayments: [], balances: { me: -100, a: 100 }, transfers: [transfer], settle: { started: true, started_at: '2026-01-01' }, obligations: [{ ...transfer, id: 'o', status: 'open', created_at: '2026-02-01' }], activity: Array.from({ length: 5 }, (_, i) => ({ id: String(i), summary: `Expense ${i}`, kind: 'add_expense', at: `2026-02-0${i + 1}`, amount_minor: 100 })) };
  render(<BalancesPanel group={group} me={members[0]} />);
  expect(screen.getByText('Updated')).toBeInTheDocument();
  expect(screen.getByText('Changed since settling')).toBeInTheDocument();
  expect(screen.getByText('Expense 4 · $1.00')).toBeInTheDocument();
  expect(screen.queryByText('Expense 1 · $1.00')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '+2 more' })).toBeInTheDocument();
});
