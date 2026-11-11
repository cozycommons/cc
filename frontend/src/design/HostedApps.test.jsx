import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CozyWabiLanding from './CozyWabiLanding.jsx';
const state = vi.hoisted(() => ({ status: 'signed-in', user: { id: 'me' }, profile: { display_name: 'Me' } }));
vi.mock('../components/commonsIdentity.js', () => ({ useCommonsIdentity: () => state, signInToCommons: vi.fn(), signOutOfCommons: vi.fn() }));
vi.mock('../supabase.js', () => ({ getClient: () => ({ auth: { getSession: async () => ({ data: { session: { access_token: 'test', user: { id: 'me' } } } }) } }) }));
beforeEach(() => { state.status = 'signed-in'; state.user = { id: 'me' }; });
afterEach(() => vi.unstubAllGlobals());
it('shows accessible hosted apps with a badge, and clears them on sign-out', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [{ name: 'jason-health', status: 'running', url: 'https://jason-health.cozycommons.dev' }] }));
  const { rerender } = render(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
  const app = await screen.findByRole('link', { name: /Jason Health/ });
  expect(app).toHaveAttribute('href', 'https://jason-health.cozycommons.dev');
  expect(screen.getByText('App')).toBeVisible();
  state.status = 'signed-out'; state.user = null;
  rerender(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
  await waitFor(() => expect(screen.queryByRole('link', { name: /Jason Health/ })).not.toBeInTheDocument());
});

it('does not fetch apps with a session belonging to another account', async () => {
  state.status = 'signed-in'; state.user = { id: 'other' };
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByText('Jason Health')).not.toBeInTheDocument();
});

it('ignores a delayed catalog response after switching accounts', async () => {
  let resolve;
  const fetcher = vi.fn(() => new Promise((done) => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher);
  const { rerender } = render(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  state.user = { id: 'other' };
  rerender(<MemoryRouter><CozyWabiLanding /></MemoryRouter>);
  await act(async () => resolve({ ok: true, json: async () => [{ name: 'private-old-app', status: 'running', url: 'https://private-old-app.cozycommons.dev' }] }));
  expect(screen.queryByText('Private Old App')).not.toBeInTheDocument();
});
