import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';
import { SNAPSHOT_V2 } from './fixture.js';

const auth = vi.hoisted(() => ({ session: { access_token: 'admin' }, listener: null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));
vi.mock('../supabase', () => ({ auth: {
  getSession: async () => auth.session,
  onAuthStateChange: callback => { auth.listener = callback; return { data: { subscription: { unsubscribe() {} } } }; },
} }));
vi.mock('./claims.js', async original => ({ ...(await original()), signedInToken: async () => auth.session?.access_token || null }));
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 403, json: async () => body });
function setup(handler = () => response({ season: 2027, espn_league_id: null })) {
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    if (url.endsWith('/predictions/latest')) return response(structuredClone(SNAPSHOT_V2));
    if (url.includes('/public/claims')) return response([]);
    if (url.endsWith('/espn/admin')) return response({ is_admin: true }, options.headers.Authorization === 'Bearer admin');
    if (url.includes('/admin/leagues/')) return handler(url, options);
    return response({}, false);
  }));
  render(<MemoryRouter><Fantasy /></MemoryRouter>);
}
afterEach(() => { vi.unstubAllGlobals(); auth.session = { access_token: 'admin' }; auth.listener = null; });
it('hides the entry from non-admins and unauthenticated visitors', async () => {
  auth.session = { access_token: 'member' };
  setup();
  await screen.findByRole('heading', { name: 'This week' });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/espn/admin'), expect.anything()));
  expect(screen.queryByRole('button', { name: 'Admin' })).toBeNull();
  act(() => auth.listener('SIGNED_OUT', null));
  expect(screen.queryByRole('button', { name: 'Admin' })).toBeNull();
  expect(fetch.mock.calls.some(([url]) => url.includes('/admin/leagues/'))).toBe(false);
});
it('loads, saves, verifies and clears settings on sign-out', async () => {
  setup((_url, options) => response(options.method === 'PUT' ? { saved: true } : { espn_league_id: '111' }));
  const entry = await screen.findByRole('button', { name: 'Admin' });
  expect(entry).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByLabelText('ESPN league ID')).toBeNull();
  fireEvent.click(entry);
  expect(entry).toHaveAttribute('aria-expanded', 'true');
  const field = await screen.findByLabelText('ESPN league ID');
  await waitFor(() => expect(field.value).toBe('111'));
  fireEvent.change(field, { target: { value: '222' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await screen.findByText('Saved');
  expect(fetch).toHaveBeenCalledWith('https://api.example.test/espn/admin/leagues/2027', expect.objectContaining({ method: 'PUT', body: '{"espn_league_id":"222"}' }));
  expect(screen.getByRole('link', { name: /Open league/ }).href).toContain('leagueId=222&seasonId=2027');
  act(() => auth.listener('SIGNED_OUT', null));
  expect(screen.queryByLabelText('ESPN league ID')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Admin' })).toBeNull();
});
it('ignores a season response that arrives after changing season', async () => {
  let resolveOld;
  setup(url => url.endsWith('/2027') ? new Promise(resolve => { resolveOld = resolve; }) : response({ espn_league_id: '222' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Admin' }));
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
  // Programmatic change exercises the race even though fields disable during load.
  fireEvent.change(screen.getByLabelText('Season'), { target: { value: '2028' } });
  await waitFor(() => expect(screen.getByLabelText('ESPN league ID').value).toBe('222'));
  await act(async () => resolveOld(response({ espn_league_id: '111' })));
  expect(screen.getByLabelText('ESPN league ID').value).toBe('222');
});
it('shows a fixed error on a failed save', async () => {
  setup((_url, options) => response({ espn_league_id: '111' }, options.method !== 'PUT'));
  fireEvent.click(await screen.findByRole('button', { name: 'Admin' }));
  await waitFor(() => expect(screen.getByLabelText('ESPN league ID').value).toBe('111'));
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await screen.findByText('Could not save. Try again.');
  expect(screen.queryByText('Saved')).toBeNull();
});

// Simulate an OAuth return so the lazy auth facade initializes the mocked client.
beforeEach(() => { window.history.replaceState({}, '', '/fantasy?code=synthetic'); });
afterEach(() => { window.history.replaceState({}, '', '/'); });
