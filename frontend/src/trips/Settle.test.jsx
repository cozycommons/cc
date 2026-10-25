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
