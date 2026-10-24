// Mirrors ledger.paid_amounts: several payers, or paid_by covering the whole expense.
export const paidAmounts = (expense) => expense.payers || { [expense.paid_by]: expense.amount_minor };
// [member, amount] for everyone who paid, in trip order (stored key order is not stable).
export const payersOf = (group, expense) => { const paid = paidAmounts(expense); return group.members.filter((m) => paid[m.id]).map((m) => [m, paid[m.id]]); };

// Who owes whom within one expense. Each shortfall is spread over the people who overpaid in proportion
// to what they're owed; leftover cents are placed so every person's row and column still add up exactly.
// `rank` (member id -> trip position) keeps that placement stable, since stored key order is not.
export function expenseFlows(expense, rank = new Map()) {
  const paid = paidAmounts(expense);
  const position = (id) => rank.get(id) ?? rank.size;
  const net = [...new Set([...Object.keys(paid), ...Object.keys(expense.shares)])]
    .sort((a, b) => position(a) - position(b) || (a < b ? -1 : 1))
    .map((id) => [id, (paid[id] || 0) - (expense.shares[id] || 0)]);
  const creditors = net.filter(([, value]) => value > 0);
  const debtors = net.filter(([, value]) => value < 0).map(([id, value]) => [id, -value]);
  const total = creditors.reduce((sum, [, value]) => sum + value, 0);
  const cells = debtors.map(([, owe]) => creditors.map(([, due]) => Math.floor((owe * due) / total)));
  const rowLeft = debtors.map(([, owe], i) => owe - cells[i].reduce((a, b) => a + b, 0));
  const colLeft = creditors.map(([, due], j) => due - cells.reduce((sum, row) => sum + row[j], 0));
  for (let i = 0, j = 0; i < debtors.length && j < creditors.length;) {
    const add = Math.min(rowLeft[i], colLeft[j]);
    cells[i][j] += add; rowLeft[i] -= add; colLeft[j] -= add;
    if (!rowLeft[i]) i += 1; else j += 1;
  }
  return debtors.flatMap(([from], i) => creditors.map(([to], j) => ({ from, to, amount: cells[i][j] }))).filter((flow) => flow.amount);
}

// Direct relationships explain the ledger; suggested transfers settle group nets.
export function balanceBreakdown(group, memberId) {
  let paid = 0, share = 0, sent = 0, received = 0;
  const direct = Object.fromEntries(group.members.filter(m => m.id !== memberId).map(m => [m.id, 0]));
  const rank = new Map(group.members.map((m, index) => [m.id, index]));
  for (const expense of group.expenses) {
    const ownPaid = paidAmounts(expense)[memberId] || 0;
    if (!ownPaid && expense.shares[memberId] === undefined) continue;
    share += expense.shares[memberId] || 0;
    paid += ownPaid;
    for (const { from, to, amount } of expenseFlows(expense, rank)) {
      if (from === memberId) direct[to] += amount;
      else if (to === memberId) direct[from] -= amount;
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
