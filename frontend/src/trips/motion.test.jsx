import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { BalancesPanel } from './Settle.jsx';

afterEach(cleanup);

const group = (balance) => ({ id: 't', name: 'Trip', currency: 'USD', revision: 1, expenses: [], repayments: [],
  members: [{ id: 'me', user_id: 'u', name: 'Matt' }, { id: 'sam', user_id: null, name: 'Sam' }],
  balances: { me: balance, sam: -balance }, transfers: balance ? [{ from_member: balance < 0 ? 'me' : 'sam', to_member: balance < 0 ? 'sam' : 'me', amount_minor: Math.abs(balance) }] : [] });
const panel = (balance) => <BalancesPanel group={group(balance)} me={{ id: 'me' }} profile={{}} onVenmo={() => {}} onRecord={() => {}} onRemoveRepayment={() => {}} onEditProfile={() => {}} />;

it('celebrates only the moment my balance becomes square', () => {
  const { rerender } = render(panel(0));
  const hero = () => screen.getByRole('region', { name: 'Your balance' });
  expect(hero()).not.toHaveClass('trips-hero--celebrate');
  rerender(panel(-500));
  expect(hero()).not.toHaveClass('trips-hero--celebrate');
  rerender(panel(0));
  expect(hero()).toHaveClass('trips-hero--celebrate');
  expect(hero()).toHaveTextContent('You’re all square');
});
