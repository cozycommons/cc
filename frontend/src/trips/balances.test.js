import { expect, it } from 'vitest';
import { balanceBreakdown } from './balances.js';

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
