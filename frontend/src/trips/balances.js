// Direct relationships explain the ledger; suggested transfers settle group nets.
export function balanceBreakdown(group, memberId) {
  let paid = 0, share = 0, sent = 0, received = 0;
  const direct = Object.fromEntries(group.members.filter(m => m.id !== memberId).map(m => [m.id, 0]));
  for (const expense of group.expenses) {
    const ownShare = expense.shares[memberId] || 0;
    share += ownShare;
    if (expense.paid_by === memberId) {
      paid += expense.amount_minor;
      for (const [id, amount] of Object.entries(expense.shares)) {
        if (id !== memberId) direct[id] -= amount;
      }
    } else {
      direct[expense.paid_by] += ownShare;
    }
  }
  for (const repayment of group.repayments) {
    if (repayment.from_member === memberId) {
      sent += repayment.amount_minor;
      direct[repayment.to_member] -= repayment.amount_minor;
    } else if (repayment.to_member === memberId) {
      received += repayment.amount_minor;
      direct[repayment.from_member] += repayment.amount_minor;
    }
  }
  return { paid, share, sent, received, net: paid - share + sent - received,
    direct: Object.entries(direct).filter(([, amount]) => amount).map(([member_id, amount_minor]) => ({ member_id, amount_minor })) };
}
