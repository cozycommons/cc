import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';
import { SNAPSHOT_V2 } from './fixture.js';

const auth = vi.hoisted(() => ({ session: { access_token: 'first' }, listener: null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));
vi.mock('../supabase', () => ({ auth: {
  getSession: async () => auth.session,
  onAuthStateChange: callback => { auth.listener = callback; return { data: { subscription: { unsubscribe() {} } } }; },
} }));
vi.mock('./claims.js', async importOriginal => ({ ...(await importOriginal()), signedInToken: async () => auth.session?.access_token || null }));
const json = body => ({ ok: true, json: async () => body });
// The hub renders every card before the links resolve; match the 10s findByRole waits below.
const SLOW = 15000;
const links = { season: 2027, team_id: 1, team: 'https://fantasy.espn.com/basketball/team?leagueId=synthetic',
  lineup: 'https://fantasy.espn.com/basketball/team?leagueId=synthetic', free_agents: 'https://fantasy.espn.com/basketball/players/add?leagueId=synthetic',
  matchups: { 1: 'https://fantasy.espn.com/basketball/boxscore?leagueId=synthetic' } };
function view(handler = async () => json(links)) {
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (url.endsWith('/predictions/latest')) return json(structuredClone(SNAPSHOT_V2));
    if (url.includes('/public/claims')) return json([]);
    if (url.endsWith('/claims/suggestions')) return json({ season: 2027, has_profile: true, mine: { team_id: 1 }, teams: [] });
    if (url.endsWith('/claims/links')) return handler(options);
    return { ok: false, json: async () => ({}) };
  }));
  // League links live on the viewer's own matchup page (team 1 plays in 1-2).
  render(<MemoryRouter initialEntries={['/fantasy/1-2']}><Routes><Route path="/fantasy/*" element={<Fantasy />} /></Routes></MemoryRouter>);
}
afterEach(() => { vi.unstubAllGlobals(); auth.session = { access_token: 'first' }; auth.listener = null; });
it('clears league links on sign-out', async () => {
  view();
  await screen.findByRole('link', { name: 'Free agents' }, { timeout: 10000 });
  await waitFor(() => expect(auth.listener).toBeTypeOf('function'));
  act(() => { auth.session = null; auth.listener('SIGNED_OUT', null); });
  expect(screen.queryByRole('link', { name: 'Free agents' })).toBeNull();
  expect(document.querySelector('a[href*="leagueId"]')).toBeNull();
}, SLOW);
it('clears the former account links while loading a new account', async () => {
  let resolve;
  view(options => options.headers.Authorization === 'Bearer first' ? json(links) : new Promise(r => { resolve = r; }));
  await screen.findByRole('link', { name: 'Free agents' }, { timeout: 10000 });
  await waitFor(() => expect(auth.listener).toBeTypeOf('function'));
  act(() => { auth.listener('SIGNED_IN', { access_token: 'second' }); });
  expect(document.querySelector('a[href*="leagueId"]')).toBeNull();
  await act(async () => { resolve({ ok: false, json: async () => ({}) }); });
  expect(document.querySelector('a[href*="leagueId"]')).toBeNull();
}, SLOW);
it('ignores a links response that arrives after sign-out', async () => {
  let resolve;
  view(() => new Promise(r => { resolve = r; }));
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  await waitFor(() => expect(auth.listener).toBeTypeOf('function'));
  await act(async () => { auth.listener('SIGNED_OUT', null); resolve(json(links)); });
  expect(document.querySelector('a[href*="leagueId"]')).toBeNull();
}, SLOW);

// Simulate an OAuth return so the lazy auth facade initializes the mocked client.
beforeEach(() => { window.history.replaceState({}, '', '/fantasy?code=synthetic'); });
afterEach(() => { window.history.replaceState({}, '', '/'); });
