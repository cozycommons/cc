import { describe, expect, it } from 'vitest';
import { normalizeUsername, settlementRole, tripNote, venmoAppLink, venmoLink, venmoProfile } from './venmo.js';

describe('Venmo usernames', () => {
  it.each([['@Jayce-e', 'Jayce-e'], [' keungjason ', 'keungjason'], ['https://venmo.com/u/bchen0702', 'bchen0702'],
    ['venmo.com/andsohn?txn=pay', 'andsohn'], ['', ''], ['@', '']])('normalizes %s', (raw, expected) => {
    expect(normalizeUsername(raw)).toBe(expected);
  });
  it.each(['abc', 'a'.repeat(31), 'has space', '@@double', 'semi;colon', 'émile-x'])('rejects %s', (raw) => {
    expect(() => normalizeUsername(raw)).toThrow('5–30 letters');
  });
});

describe('settlement direction', () => {
  const transfer = { from_member: 'debtor', to_member: 'creditor', amount_minor: 19818 };
  it('lets the debtor pay and the creditor request, and offers nothing to anyone else', () => {
    expect(settlementRole(transfer, 'debtor')).toBe('pay');
    expect(settlementRole(transfer, 'creditor')).toBe('request');
    expect(settlementRole(transfer, 'bystander')).toBeNull();
    expect(settlementRole(transfer, undefined)).toBeNull();
  });
});

describe('Venmo links', () => {
  it('encodes action, exact amount and a note with symbols', () => {
    const note = tripNote('Tahoe & Reno #2 🏔️');
    const url = new URL(venmoLink({ username: 'Jayce-e', role: 'pay', amountMinor: 19818, note }));
    expect(url.origin + url.pathname).toBe('https://venmo.com/Jayce-e');
    expect(url.searchParams.get('txn')).toBe('pay');
    expect(url.searchParams.get('amount')).toBe('198.18');
    expect(url.searchParams.get('note')).toBe('Cozy Trips · Tahoe & Reno #2 🏔️');
    expect(url.search).not.toContain('+');
    expect(url.search).toContain('note=Cozy%20Trips%20%C2%B7%20Tahoe%20%26%20Reno%20%232%20');
    expect([...url.searchParams.keys()]).toEqual(['txn', 'amount', 'note']);
  });
  it('uses charge for requests and keeps whole-dollar cents', () => {
    const url = new URL(venmoLink({ username: 'mattsho', role: 'request', amountMinor: 500, note: 'x' }));
    expect(url.searchParams.get('txn')).toBe('charge');
    expect(url.searchParams.get('amount')).toBe('5.00');
  });
  it('keeps spaces and literal plus signs distinct in the native app note', () => {
    const link = venmoLink({ username: 'andsohn', role: 'pay', amountMinor: 19818, note: tripNote('NITEHARTS 26 + friends') });
    const note = link.split('note=')[1];
    expect(note).not.toContain('+');
    expect(note).toBe('Cozy%20Trips%20%C2%B7%20NITEHARTS%2026%20%2B%20friends');
    expect(decodeURIComponent(note)).toBe('Cozy Trips · NITEHARTS 26 + friends');
  });
});

describe('Venmo profiles', () => {
  it('links to the public profile so people can check the name before paying', () => {
    expect(venmoProfile('MattSHo')).toBe('https://venmo.com/u/MattSHo');
    expect(venmoProfile('jayce-e')).toBe('https://venmo.com/u/jayce-e');
  });
});

describe('venmoAppLink', () => {
  it('opens the Venmo app to the exact prefilled payment with %20 spaces', () => {
    expect(venmoAppLink({ username: 'alex-rivera', role: 'pay', amountMinor: 1234, note: 'Cozy Trips · Cabin', reference: 'CZ-0001' }))
      .toBe('venmo://paycharge?txn=pay&recipients=alex-rivera&amount=12.34&note=Cozy%20Trips%20%C2%B7%20Cabin%20%C2%B7%20CZ-0001');
    expect(venmoAppLink({ username: 'alex-rivera', role: 'request', amountMinor: 500, note: 'Cozy Trips · Cabin' }))
      .toBe('venmo://paycharge?txn=charge&recipients=alex-rivera&amount=5.00&note=Cozy%20Trips%20%C2%B7%20Cabin');
  });
});
