export const currencies = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'MXN'];

export function toMinor(value, allowZero = false) {
  const text = String(value).trim();
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(text)) throw new Error('Enter an amount with up to two decimal places.');
  const [whole, fraction = ''] = text.split('.');
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
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
