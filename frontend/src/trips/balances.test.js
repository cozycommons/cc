import { expect, it } from 'vitest';
import { balanceBreakdown, expenseFlows } from './balances.js';

const group = () => ({ members: ['me', 'friend-a', 'friend-b'].map(id => ({ id })), repayments: [], expenses: [
  { paid_by: 'me', amount_minor: 12000, shares: { me: 4000, 'friend-a': 4000, 'friend-b': 4000 } },
  { paid_by: 'friend-a', amount_minor: 15000, shares: { me: 5000, 'friend-a': 5000, 'friend-b': 5000 } },
  { paid_by: 'friend-b', amount_minor: 9000, shares: { me: 3000, 'friend-a': 3000, 'friend-b': 3000 } },
] });

it('explains direct debts even when their group net cancels to zero', () => {
  expect(balanceBreakdown(group(), 'me')).toEqual({ paid: 12000, share: 12000, sent: 0, received: 0, net: 0,
    direct: [{ member_id: 'friend-a', amount_minor: 1000 }, { member_id: 'friend-b', amount_minor: -1000 }] });
});

it('includes both repayment directions and reconciles direct rows with the group net', () => {
  const data = group();
  data.repayments = [
    { from_member: 'me', to_member: 'friend-a', amount_minor: 500 },
    { from_member: 'friend-b', to_member: 'me', amount_minor: 200 },
    { from_member: 'friend-a', to_member: 'friend-b', amount_minor: 700 },
  ];
  const result = balanceBreakdown(data, 'me');
  expect(result).toMatchObject({ sent: 500, received: 200, net: 300 });
  expect(result.direct).toEqual([{ member_id: 'friend-a', amount_minor: 500 }, { member_id: 'friend-b', amount_minor: -800 }]);
  expect(result.direct.reduce((total, row) => total + row.amount_minor, 0)).toBe(-result.net);
});

it('handles an expense where the payer is not a participant and excludes unrelated shares', () => {
  const data = group();
  data.expenses = [{ paid_by: 'me', amount_minor: 701, shares: { 'friend-a': 701 } },
    { paid_by: 'friend-b', amount_minor: 999, shares: { 'friend-a': 999 } }];
  expect(balanceBreakdown(data, 'me')).toMatchObject({ paid: 701, share: 0, net: 701,
    direct: [{ member_id: 'friend-a', amount_minor: -701 }] });
});

it('spreads a several-payer expense exactly to the cent, matching each person’s net', () => {
  // $100 paid 70/30, split three ways: nets are +36.66, -3.33, -33.33 with an odd cent to place.
  const expense = { paid_by: 'a', payers: { a: 7000, b: 3000 }, amount_minor: 10000, shares: { a: 3334, b: 3333, c: 3333 } };
  const flows = expenseFlows(expense);
  const total = (id, side) => flows.filter((f) => f[side] === id).reduce((sum, f) => sum + f.amount, 0);
  expect(total('a', 'to')).toBe(3666);
  expect(total('b', 'from')).toBe(333);
  expect(total('c', 'from')).toBe(3333);
  const group = { members: ['a', 'b', 'c'].map((id) => ({ id })), repayments: [], expenses: [expense] };
  for (const id of ['a', 'b', 'c']) {
    const { net, direct } = balanceBreakdown(group, id);
    expect(-direct.reduce((sum, row) => sum + row.amount_minor, 0)).toBe(net);
  }
});

it('keeps one-payer expenses exactly as before', () => {
  const expense = { paid_by: 'a', amount_minor: 9000, shares: { a: 3000, b: 3000, c: 3000 } };
  expect(expenseFlows(expense)).toEqual([{ from: 'b', to: 'a', amount: 3000 }, { from: 'c', to: 'a', amount: 3000 }]);
});

it('places leftover cents by member order, not stored key order', () => {
  const a = { paid_by: 'b', payers: { a: 1, b: 1 }, amount_minor: 2, shares: { c: 1, d: 1 } };
  const b = { paid_by: 'b', payers: { b: 1, a: 1 }, amount_minor: 2, shares: { d: 1, c: 1 } };
  const order = new Map(['b', 'a', 'd', 'c'].map((id, index) => [id, index]));
  expect(expenseFlows(a, order)).toEqual(expenseFlows(b, order));
  expect(expenseFlows(a, order)).toEqual([{ from: 'd', to: 'b', amount: 1 }, { from: 'c', to: 'a', amount: 1 }]);
});
