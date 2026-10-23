import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
function signedIn() {
  mocked.auth.user = { id: 'user-a', user_metadata: { full_name: 'Account name' } };
  mocked.auth.profile = { user_id: 'user-a', display_name: 'Existing Dice name', avatar_url: '/avatar.png' };
}

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
  expect(screen.getByText('Joining as Existing Dice name with your Commons account.')).toBeInTheDocument();
});

it('uses the retained invitation after OAuth and navigates after joining', async () => {
  signedIn();
  sessionStorage.setItem('cozy-trips-invite:trip-id', 'retained-secret');
  mocked.request.mockImplementation((_client, path) => Promise.resolve(path.endsWith('/join') ? { id: 'trip-id' } : []));
  open('/trips/join/trip-id#access_token=oauth-callback');
  fireEvent.click(screen.getByRole('button', { name: 'Join trip', exact: true }));
  expect(await screen.findByText('Trip opened')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith(mocked.auth.supabase, '/groups/trip-id/join', 'POST', { invite_token: 'retained-secret' });
  expect(sessionStorage.getItem('cozy-trips-invite:trip-id')).toBeNull();
});

it('shows a missing invitation error without submitting a join', async () => {
  signedIn();
  mocked.request.mockResolvedValue([]);
  open('/trips/join/trip-id');
  fireEvent.click(screen.getByRole('button', { name: 'Join trip', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('missing its secret');
  expect(mocked.request.mock.calls.some(call => call[2] === 'POST')).toBe(false);
});

it('survives blocked invitation storage and a successful join cleanup', async () => {
  signedIn();
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked'); });
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Blocked'); });
  mocked.request.mockImplementation((_client, path) => Promise.resolve(path.endsWith('/join') ? { id: 'trip-id' } : []));
  open('/trips/join/trip-id#invite=link-secret');
  fireEvent.click(screen.getByRole('button', { name: 'Join trip', exact: true }));
  expect(await screen.findByText('Trip opened')).toBeInTheDocument();
});

it('offers a retry after a trip list network failure', async () => {
  signedIn();
  mocked.request.mockRejectedValueOnce(new Error('Connection interrupted')).mockResolvedValueOnce([]);
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Your trips' })).toBeInTheDocument());
});
