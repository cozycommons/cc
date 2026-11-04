import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Account from './Account.jsx';

const mocked = vi.hoisted(() => ({ identity: null, request: vi.fn(), shown: vi.fn(), signIn: vi.fn() }));
vi.mock('../components/commonsIdentity.js', () => ({
  useCommonsIdentity: () => mocked.identity,
  accountRequest: (...args) => mocked.request(...args),
  showCommonsProfile: (...args) => mocked.shown(...args),
  signInToCommons: (...args) => mocked.signIn(...args),
  signOutOfCommons: vi.fn(),
  commonsSupabase: () => null,
}));

const sam = { user_id: 'u1', display_name: 'Sam', email: 'sam@example.test', avatar_url: null };
const claude = { id: 'c1', client_name: 'Claude', redirect_host: 'claude.ai', scopes: ['commons:read', 'commons:edit'],
  approved_at: '2026-10-04T12:00:00Z', last_used_at: '2026-11-02T12:00:00Z' };

beforeEach(() => {
  mocked.identity = { status: 'signed-in', user: { id: 'u1' }, profile: sam };
  mocked.request.mockReset(); mocked.shown.mockReset(); mocked.signIn.mockReset();
});
afterEach(cleanup);
const open = () => render(<MemoryRouter initialEntries={['/account']}><Account /></MemoryRouter>);

it('asks signed-out visitors to sign in', () => {
  mocked.identity = { status: 'signed-out', user: null, profile: null };
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
  expect(mocked.signIn).toHaveBeenCalled();
  expect(mocked.request).not.toHaveBeenCalled();
});

it('renames the Commons profile and shows it in the header', async () => {
  mocked.request.mockImplementation(async (path) => (path === '/connections' ? [] : { ...sam, display_name: 'Sam H' }));
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Edit name' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Display name' }), { target: { value: '  Sam H ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(mocked.shown).toHaveBeenCalledWith(expect.objectContaining({ display_name: 'Sam H' })));
  expect(mocked.request).toHaveBeenCalledWith('/profile', { method: 'PATCH', body: { display_name: 'Sam H' } });
  expect(await screen.findByRole('button', { name: 'Edit name' })).toBeInTheDocument();
});

it('lists connected agents and disconnects one after confirming', async () => {
  mocked.request.mockImplementation(async (path) => (path === '/connections' ? [claude] : null));
  open();
  const row = (await screen.findByText('Claude')).closest('li');
  expect(row).toHaveTextContent('claude.ai');
  expect(row).toHaveTextContent('Read and save changes');
  fireEvent.click(within(row).getByRole('button', { name: 'Disconnect' }));
  fireEvent.click(within(row).getByRole('button', { name: 'Disconnect Claude' }));
  await waitFor(() => expect(screen.queryByText('Claude')).not.toBeInTheDocument());
  expect(mocked.request).toHaveBeenCalledWith('/connections/c1', { method: 'DELETE' });
  expect(screen.getByText('No agents connected.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Setup steps' })).toHaveAttribute('href', '/connect');
});

it('shows why connections are unavailable and keeps the profile usable', async () => {
  mocked.request.mockRejectedValue(new Error('Agent connections are unavailable.'));
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Agent connections are unavailable.');
  expect(screen.getByRole('button', { name: 'Edit name' })).toBeInTheDocument();
});
