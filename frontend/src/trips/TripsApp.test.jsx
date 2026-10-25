import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import TripsApp from './TripsApp.jsx';

const mocked = vi.hoisted(() => ({ auth: null, request: vi.fn() }));
vi.mock('./useTripsAuth.js', () => ({ useTripsAuth: () => mocked.auth, localDemo: false }));
vi.mock('./api.js', () => ({ tripRequest: (...args) => mocked.request(...args) }));
// These tests exercise route/auth/form behavior. Native dialog focus is covered
// by the browser acceptance run; jsdom does not implement showModal().
vi.mock('./ui.jsx', async importOriginal => ({ ...await importOriginal(),
  Modal: ({ title, children }) => <section role="dialog" aria-label={title}>{children}</section>,
}));

beforeEach(() => {
  mocked.request.mockReset();
  vi.stubGlobal('scrollTo', vi.fn());
  window.history.replaceState({}, '', '/trips');
  sessionStorage.clear();
  mocked.auth = { loading: false, user: null, profile: null, error: '', supabase: {},
    signIn: vi.fn(), signOut: vi.fn().mockResolvedValue({}) };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function open(path = '/trips') {
  window.history.replaceState({}, '', path);
  return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/trips/join/:tripId" element={<TripsApp />} />
    <Route path="/trips" element={<TripsApp />} />
    <Route path="/trips/:tripId" element={<p>Trip opened</p>} />
  </Routes></MemoryRouter>);
}
const invitePreview = { already_member: false, trip_name: 'Tahoe weekend', currency: 'USD', inviter: 'Matt',
  member_name: 'Alex', member_count: 3, balance_minor: -2500 };
const answer = (joined) => (_client, path) => Promise.resolve(
  path.endsWith('/invite-preview') ? invitePreview : path.endsWith('/join') ? joined : path === '/groups' ? [] : joined);
function signedIn() {
  mocked.auth.user = { id: 'user-a', user_metadata: { full_name: 'Account name' } };
  mocked.auth.profile = { user_id: 'user-a', display_name: 'Existing Dice name', avatar_url: '/avatar.png' };
}

const confirmationGroup = { id: 'trip-id', name: 'Synthetic trip', owner_id: 'user-a', currency: 'USD', revision: 1,
  members: [{ id: 'me', user_id: 'user-a', name: 'Account name' }], expenses: [], repayments: [], activity: [],
  balances: { me: 0 }, transfers: [], total_minor: 0 };

it('asks a linked member once, then opens trips after the account confirmation is saved', async () => {
  signedIn();
  mocked.auth.profile = { ...mocked.auth.profile, venmo_username: 'test-handle', venmo_confirmed: false };
  mocked.auth.saveVenmo = vi.fn().mockResolvedValue({});
  mocked.request.mockResolvedValue(confirmationGroup);
  const app = () => <MemoryRouter initialEntries={['/trips/trip-id']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><TripsApp /></MemoryRouter>;
  const view = render(app());
  expect(await screen.findByRole('heading', { name: 'Confirm your Venmo' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Add expense' })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: "Yes, that's me" })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: "Yes, that's me" }));
  await waitFor(() => expect(mocked.auth.saveVenmo).toHaveBeenCalledWith('test-handle', true));
  mocked.auth.profile = { ...mocked.auth.profile, venmo_confirmed: true };
  view.rerender(app());
  expect(await screen.findByRole('button', { name: 'Add expense' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Confirm your Venmo' })).not.toBeInTheDocument();
  view.unmount();
  render(app()); // A fresh opening uses persisted account state, not browser storage.
  expect(await screen.findByRole('button', { name: 'Add expense' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Confirm your Venmo' })).not.toBeInTheDocument();
});

it('does not ask the creator to confirm another member’s Venmo', async () => {
  signedIn();
  mocked.auth.profile = { ...mocked.auth.profile, venmo_confirmed: true };
  mocked.request.mockResolvedValue({ ...confirmationGroup, members: [...confirmationGroup.members,
    { id: 'other', user_id: 'user-b', name: 'Other', venmo_username: 'other-handle', venmo_confirmed: false }] });
  render(<MemoryRouter initialEntries={['/trips/trip-id']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><TripsApp /></MemoryRouter>);
  expect(await screen.findByRole('button', { name: 'Add expense' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Confirm your Venmo' })).not.toBeInTheDocument();
});

it('waits for the caller’s profile before opening a linked trip or its deep-linked editor', async () => {
  signedIn();
  mocked.auth.profile = null;
  mocked.request.mockResolvedValue(confirmationGroup);
  const app = () => <MemoryRouter initialEntries={['/trips/trip-id?add=expense']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><TripsApp /></MemoryRouter>;
  const view = render(app());
  expect(await screen.findByRole('status')).toHaveTextContent('Loading');
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Loading your profile'));
  expect(screen.queryByRole('button', { name: 'Add expense' })).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  mocked.auth.profile = { user_id: 'user-a', venmo_username: 'test-handle', venmo_confirmed: false };
  view.rerender(app());
  expect(screen.getByRole('heading', { name: 'Confirm your Venmo' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('keeps the invitation secret before starting shared Google sign-in', async () => {
  open('/trips/join/trip-id#invite=one-use-secret');
  expect(sessionStorage.getItem('cozy-trips-invite:trip-id')).toBe('one-use-secret');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /Continue with Google/ })));
  expect(mocked.auth.signIn).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'Continue as Matt' })).not.toBeInTheDocument();
});

it('shows the canonical shared profile and does not ask for a separate trip identity', async () => {
  signedIn();
  mocked.request.mockResolvedValue([]);
  open();
  expect(screen.getByText('Existing Dice name')).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'New trip', exact: true }));
  expect(screen.queryByLabelText('Your name')).not.toBeInTheDocument();
  expect(screen.getByText('You’ll join as Existing Dice name.')).toBeInTheDocument();
});

it('keeps the account name and photo while the shared profile is loading', async () => {
  signedIn();
  mocked.auth.profile = null;
  mocked.auth.user.user_metadata.avatar_url = '/google-avatar.png';
  mocked.request.mockResolvedValue([]);
  open();
  const identity = screen.getByRole('button', { name: 'Signed in as Account name. Open profile' });
  expect(identity).toHaveTextContent('Account name');
  expect(identity.querySelector('img')).toHaveAttribute('src', '/google-avatar.png');
  expect(screen.getByRole('button', { name: 'Sign out', exact: true })).toBeInTheDocument();
});

it('uses the retained invitation after OAuth and navigates after joining', async () => {
  signedIn();
  sessionStorage.setItem('cozy-trips-invite:trip-id', 'retained-secret');
  mocked.request.mockImplementation(answer({ id: 'trip-id' }));
  open('/trips/join/trip-id#access_token=oauth-callback');
  expect(await screen.findByRole('heading', { name: 'Tahoe weekend' })).toBeInTheDocument();
  expect(screen.getByText('Matt invited you')).toBeInTheDocument();
  expect(screen.getByText(/Alex owes \$25\.00 so far/)).toBeInTheDocument();
  expect(screen.getByText(/Not Alex\? Ask Matt for your own link/)).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith(mocked.auth.supabase, '/groups/trip-id/invite-preview', 'POST', { invite_token: 'retained-secret' });
  fireEvent.click(screen.getByRole('button', { name: 'Join as Alex' }));
  expect(await screen.findByText('Trip opened')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith(mocked.auth.supabase, '/groups/trip-id/join', 'POST', { invite_token: 'retained-secret' });
  expect(sessionStorage.getItem('cozy-trips-invite:trip-id')).toBeNull();
});

it('shows a missing invitation error without submitting a join', async () => {
  signedIn();
  mocked.request.mockResolvedValue([]);
  open('/trips/join/trip-id');
  expect(await screen.findByRole('alert')).toHaveTextContent('missing its code');
  expect(screen.queryByRole('button', { name: /Join/ })).not.toBeInTheDocument();
  expect(mocked.request.mock.calls.some(call => call[2] === 'POST')).toBe(false);
});

it('survives blocked invitation storage and a successful join cleanup', async () => {
  signedIn();
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked'); });
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Blocked'); });
  mocked.request.mockImplementation(answer({ id: 'trip-id' }));
  open('/trips/join/trip-id#invite=link-secret');
  fireEvent.click(await screen.findByRole('button', { name: 'Join as Alex' }));
  expect(await screen.findByText('Trip opened')).toBeInTheDocument();
});

it('tells a member who opens an invite that they are already on the trip, without joining', async () => {
  signedIn();
  mocked.request.mockImplementation((_client, path) => Promise.resolve(path.endsWith('/invite-preview') ? { already_member: true, trip_name: 'Tahoe weekend' } : []));
  open('/trips/join/trip-id#invite=someone-elses-link');
  expect(await screen.findByText('You’re already on this trip.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Open trip/ }));
  expect(await screen.findByText('Trip opened')).toBeInTheDocument();
  expect(mocked.request.mock.calls.some(call => call[1].endsWith('/join'))).toBe(false);
});

it('explains a used or invalid invite instead of offering to join', async () => {
  signedIn();
  mocked.request.mockImplementation((_client, path) => path.endsWith('/invite-preview')
    ? Promise.reject(new Error('This invitation is invalid or has already been used.')) : Promise.resolve([]));
  open('/trips/join/trip-id#invite=used');
  expect(await screen.findByRole('alert')).toHaveTextContent('already been used');
  expect(screen.queryByRole('button', { name: /Join/ })).not.toBeInTheDocument();
});

it('offers a retry after a trip list network failure', async () => {
  signedIn();
  mocked.request.mockRejectedValueOnce(new Error('Connection interrupted')).mockResolvedValueOnce([]);
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Your trips' })).toBeInTheDocument());
});

it('opens repeated descriptions by payer, amount and date, then edits or deletes from the detail', async () => {
  signedIn();
  const group = { id: 'trip-id', owner_id: 'user-a', name: 'Trip', currency: 'USD', revision: 1,
    members: [{ id: 'member-a', user_id: 'user-a', name: 'Owner' }, { id: 'member-b', user_id: 'user-b', name: 'Guest' }],
    balances: { 'member-a': -750, 'member-b': 750 }, total_minor: 3500, transfers: [], repayments: [], activity: [],
    expenses: [
      { id: 'first', description: 'Dinner', amount_minor: 1000, paid_by: 'member-a', date: '2026-10-22', created_at: '2026-10-22T12:00:00Z', category: 'food', notes: '', split_mode: 'equal', shares: { 'member-a': 500, 'member-b': 500 } },
      { id: 'second', description: 'Dinner', amount_minor: 2500, paid_by: 'member-b', date: '2026-10-23', created_at: '2026-10-23T12:00:00Z', category: 'food', notes: '', split_mode: 'equal', shares: { 'member-a': 1250, 'member-b': 1250 } },
    ] };
  mocked.request.mockResolvedValue(group);
  render(<MemoryRouter initialEntries={['/trips/trip-id']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/trips/:tripId" element={<TripsApp />} />
  </Routes></MemoryRouter>);
  const row = await screen.findByRole('button', { name: 'Open Dinner, $25.00 paid by Guest on 2026-10-23', exact: true });
  expect(screen.getByRole('button', { name: 'Open Dinner, $10.00 paid by Owner on 2026-10-22', exact: true })).toBeInTheDocument();
  fireEvent.click(row);
  const detail = screen.getByRole('dialog', { name: 'Dinner' });
  expect(detail).toHaveTextContent('$25.00');
  expect(detail).toHaveTextContent('Guest paid · split equally');
  expect(screen.queryByLabelText('Description')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  expect(screen.getByLabelText('Description')).toHaveValue('Dinner');
  expect(screen.getByLabelText('Amount (USD)')).toHaveValue('25.00');
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  expect(screen.getByRole('dialog', { name: 'Delete this expense?' })).toHaveTextContent('Dinner · $25.00');
});

it('ignores an old trip save after navigating to a different trip', async () => {
  signedIn();
  const empty = (id, name) => ({ id, name, owner_id: 'user-a', currency: 'USD', revision: 1,
    members: [{ id: 'member-a', user_id: 'user-a', name: 'Owner' }],
    expenses: [], repayments: [], transfers: [], activity: [], balances: { 'member-a': 0 }, total_minor: 0 });
  const first = empty('first', 'First trip');
  const second = empty('second', 'Second trip');
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  mocked.request.mockImplementation((_client, path, method) => method === 'POST' ? pending : Promise.resolve(path.endsWith('/first') ? first : second));
  render(<MemoryRouter initialEntries={['/trips/first']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/trips/:tripId" element={<><Link to="/trips/second">Open second trip</Link><TripsApp /></>} />
  </Routes></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Add expense', exact: true }));
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Dinner' } });
  fireEvent.change(screen.getByLabelText('Amount (USD)'), { target: { value: '10.00' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  fireEvent.click(screen.getByRole('link', { name: 'Open second trip' }));
  expect(await screen.findByRole('heading', { name: 'Second trip' })).toBeInTheDocument();
  await act(async () => { finish({ ...first, revision: 2 }); await pending; });
  expect(screen.getByRole('heading', { name: 'Second trip' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'First trip' })).not.toBeInTheDocument();
});

it('opens the joined trip itself after accepting an invite, not the trip list', async () => {
  signedIn();
  sessionStorage.setItem('cozy-trips-invite:trip-id', 'retained-secret');
  const trip = { id: 'trip-id', owner_id: 'owner', name: 'Joined trip', currency: 'USD', revision: 2, created_at: '2026-10-01',
    members: [{ id: 'm1', user_id: 'owner', name: 'Owner' }, { id: 'm2', user_id: 'user-a', name: 'Me' }],
    balances: { m1: 0, m2: 0 }, transfers: [], expenses: [], repayments: [], activity: [], total_minor: 0 };
  mocked.request.mockImplementation(answer(trip));
  render(<MemoryRouter initialEntries={['/trips/join/trip-id']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/trips/join/:tripId" element={<TripsApp />} />
    <Route path="/trips/:tripId" element={<TripsApp />} />
  </Routes></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Join as Alex' }));
  expect(await screen.findByRole('heading', { name: 'Joined trip' })).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'Balances', selected: true })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Your trips' })).not.toBeInTheDocument();
});
