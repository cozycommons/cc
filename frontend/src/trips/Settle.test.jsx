import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
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
    ? 'The fewest payments that square everyone up, with the least money changing hands, so you might pay someone other than who covered you.'
    : 'These square everyone up with the least money changing hands, so you might pay someone other than who covered you.';
  expect(screen.getByText(note)).toBeInTheDocument();
  if (settlement !== 'fewest') expect(screen.queryByText(/fewest payments/)).not.toBeInTheDocument();
});
