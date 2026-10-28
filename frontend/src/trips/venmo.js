import { decimal } from './money.js';

// Mirrors backend/venmo/usernames.py. Usernames are display data, never proof of identity.
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

export const tripNote =(groupName) => `Cozy Trips · ${groupName}`;

// The native Venmo app displays form-encoded '+' spaces literally, so encode with %20.
const query = (params) => Object.entries(params).map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&');
const fullNote = (note, reference) => (reference ? `${note} · ${reference}` : note);

// Web payment link, for computers. Venmo's app doesn't claim these paths, so on phones they stay in the browser.
export function venmoLink({ username, role, amountMinor, note, reference }) {
  return `https://venmo.com/${encodeURIComponent(username)}?${query({ txn: role === 'request' ? 'charge' : 'pay', amount: decimal(amountMinor), note: fullNote(note, reference) })}`;
}

// Opens the Venmo app straight to a prefilled payment or request. Prefill is best-effort; the person reviews it there.
export function venmoAppLink({ username, role, amountMinor, note, reference }) {
  return `venmo://paycharge?${query({ txn: role === 'request' ? 'charge' : 'pay', recipients: username, amount: decimal(amountMinor), note: fullNote(note, reference) })}`;
}

export const isPhone = () => typeof navigator !== 'undefined'
  && (/iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));
