import React from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const supabase = vi.hoisted(() => ({ session: null, listener: null, fail: false }));
vi.mock('../supabase.js', () => ({
  getClient: () => {
    if (supabase.fail) throw new Error('VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY is missing');
    return { auth: {
      getSession: async () => ({ data: { session: supabase.session } }),
      onAuthStateChange: (callback) => { supabase.listener = callback; return { data: { subscription: { unsubscribe() {} } } }; },
    } };
  },
}));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.test' }));

import { refreshCommonsIdentity, resetCommonsIdentityForTests, useCommonsIdentity } from './commonsIdentity.js';

function Who() {
  const { status, profile } = useCommonsIdentity();
  return <output>{status}:{profile?.display_name || ''}:{profile?.avatar_url || ''}</output>;
}
const sam = { id: 'u1', email: 'sam@example.test', user_metadata: { full_name: 'Google Sam', avatar_url: 'https://google.test/s.png' } };

beforeEach(() => {
  resetCommonsIdentityForTests();
  Object.assign(supabase, { session: null, listener: null, fail: false });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows the Google identity at once, then the Commons profile from /account', async () => {
  supabase.session = { user: sam, access_token: 'token-sam' };
  let answer;
  const fetch = vi.fn(() => new Promise((resolve) => { answer = resolve; }));
  vi.stubGlobal('fetch', fetch);
  render(<Who />);
  expect(await screen.findByText('signed-in:Google Sam:https://google.test/s.png')).toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('https://api.test/account', expect.objectContaining({
    headers: expect.objectContaining({ Authorization: 'Bearer token-sam' }) })));
  await act(async () => answer({ ok: true, status: 200, json: async () => ({ user_id: 'u1', display_name: 'Dice Sam', avatar_url: 'https://cdn.test/d.webp' }) }));
  expect(await screen.findByText('signed-in:Dice Sam:https://cdn.test/d.webp')).toBeInTheDocument();
});

it('keeps the Google identity when /account fails, and refreshes after an edit', async () => {
  supabase.session = { user: sam, access_token: 'token-sam' };
  const fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'down' }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ user_id: 'u1', display_name: 'Renamed', avatar_url: null }) });
  vi.stubGlobal('fetch', fetch);
  render(<Who />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(screen.getByText('signed-in:Google Sam:https://google.test/s.png')).toBeInTheDocument();
  await act(() => refreshCommonsIdentity());
  expect(screen.getByText('signed-in:Renamed:')).toBeInTheDocument();
});

it('treats anonymous sessions, sign-out and a missing client as signed out', async () => {
  vi.stubGlobal('fetch', vi.fn());
  supabase.session = { user: { ...sam, is_anonymous: true } };
  render(<Who />);
  expect(await screen.findByText('signed-out::')).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();

  act(() => supabase.listener('SIGNED_IN', { user: sam, access_token: 't' }));
  expect(screen.getByText(/^signed-in:Google Sam/)).toBeInTheDocument();
  act(() => supabase.listener('SIGNED_OUT', null));
  expect(screen.getByText('signed-out::')).toBeInTheDocument();

  cleanup();
  resetCommonsIdentityForTests();
  supabase.fail = true;
  render(<Who />);
  expect(await screen.findByText('signed-out::')).toBeInTheDocument();
});
