import { afterEach, expect, it, vi } from 'vitest';
import { clearInvitation, readInvitation } from './invitation.js';

afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });

it('retains the invitation when OAuth replaces the URL fragment', () => {
  expect(readInvitation('trip-1', '#invite=one-use-secret')).toBe('one-use-secret');
  expect(readInvitation('trip-1', '#access_token=oauth-callback')).toBe('one-use-secret');
  expect(readInvitation('trip-2', '#access_token=oauth-callback')).toBe('');
  clearInvitation('trip-1');
  expect(readInvitation('trip-1', '')).toBe('');
});

it('keeps the original link usable when storage is unavailable', () => {
  const storage = { setItem: vi.fn(() => { throw new Error('Blocked storage'); }), getItem: vi.fn() };
  expect(readInvitation('trip-1', '#invite=link-secret', storage)).toBe('link-secret');
  expect(storage.getItem).not.toHaveBeenCalled();
});

it('does not fail a completed join when clearing storage is unavailable', () => {
  const storage = { removeItem: () => { throw new Error('Blocked storage'); } };
  expect(() => clearInvitation('trip-1', storage)).not.toThrow();
});
