export const currencies = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'MXN'];

const symbols = { USD: '$', CAD: '$', AUD: '$', MXN: '$', EUR: '€', GBP: '£' };

export function toMinor(value, allowZero = false, currency = 'USD') {
  // Accept what people type on phones: "$12", "1,250.5", ".75". Every supported currency has two decimals.
  let text = String(value).trim();
  const symbol = text.match(/^[$€£]/)?.[0];
  if (symbol && symbol !== symbols[currency]) throw new Error(`This trip uses ${currency}. Enter the amount in ${currency}.`);
  text = text.replace(/^[$€£]\s*/, '').replace(/,(?=\d{3}(?:\D|$))/g, '');
  if (!/^(?=[\d.]*\d)\d{0,8}(\.\d{1,2})?$/.test(text)) throw new Error('Enter an amount with up to two decimal places.');
  const [whole, fraction = ''] = text.split('.');
  const amount = Number(whole || 0) * 100 + Number(fraction.padEnd(2, '0'));
  if (amount > 1_000_000_000 || amount < (allowZero ? 0 : 1)) {
    throw new Error('Enter an amount between 0.01 and 10,000,000.00.');
  }
  return amount;
}

export const decimal = (amount) => (amount / 100).toFixed(2);
export const money = (amount, currency) => new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount / 100);
export const today = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};
export const shortDate = (date) => new Date(`${date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

export function equalShares(amount, members) {
  if (!members.length) return {};
  const base = Math.floor(amount / members.length);
  return Object.fromEntries(members.map((member, index) => [member.id, base + Number(index < amount % members.length)]));
}

// Mirrors ledger.weighted_shares: leftover pennies go to the largest remainders, then member order.
export function weightedShares(amount, weights) {
  const entries = Object.entries(weights).filter(([, weight]) => weight > 0);
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
  if (!total) return {};
  const shares = Object.fromEntries(entries.map(([id, weight]) => [id, Math.floor((amount * weight) / total)]));
  const left = amount - Object.values(shares).reduce((a, b) => a + b, 0);
  const order = entries.map(([id, weight], index) => ({ id, index, rest: (amount * weight) % total }))
    .sort((a, b) => b.rest - a.rest || a.index - b.index);
  for (const { id } of order.slice(0, left)) shares[id] += 1;
  return shares;
}
