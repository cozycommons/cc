import { decimal } from './money.js';

// Mirrors backend/trips/venmo.py. Usernames are display data, never proof of identity.
const USERNAME = /^[A-Za-z0-9_-]{5,30}$/;
const PREFIX = /^(?:https?:\/\/)?(?:www\.|account\.)?venmo\.com\/(?:u\/)?/i;

export function normalizeUsername(value) {
  const text = String(value ?? '').trim().replace(PREFIX, '').split('?')[0].replace(/^\/+|\/+$/g, '').replace(/^@/, '').trim();
  if (!text) return '';
  if (!USERNAME.test(text)) throw new Error('Use 5–30 letters, numbers, hyphens, or underscores, like @alex-smith.');
  return text;
}

// The signed-in person pays when they are the debtor and requests when they are the creditor.
export function settlementRole(transfer, myMemberId) {
  if (!myMemberId) return null;
  if (transfer.from_member === myMemberId) return 'pay';
  if (transfer.to_member === myMemberId) return 'request';
  return null;
}

// Public profile page: shows the person's Venmo name and photo so people can check before paying.
export const venmoProfile = (username) => `https://venmo.com/u/${encodeURIComponent(username)}`;

export const tripNote =(groupName) => `${groupName} · Cozy Trips`;

// Venmo redirects these public links to its web app or mobile app. Prefill is best-effort; the person reviews it there.
export function venmoLink({ username, role, amountMinor, note }) {
  // The native Venmo app displays form-encoded '+' spaces literally.
  const params = Object.entries({ txn: role === 'request' ? 'charge' : 'pay', amount: decimal(amountMinor), note })
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&');
  return `https://venmo.com/${encodeURIComponent(username)}?${params}`;
}
