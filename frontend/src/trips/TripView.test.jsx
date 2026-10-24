import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import TripsApp from './TripsApp.jsx';

const mocked = vi.hoisted(() => ({ auth: null, request: vi.fn() }));
vi.mock('./useTripsAuth.js', () => ({ useTripsAuth: () => mocked.auth, localDemo: false }));
vi.mock('./api.js', () => ({ tripRequest: (...args) => mocked.request(...args) }));
vi.mock('./ui.jsx', async (importOriginal) => ({ ...await importOriginal(),
  Modal: ({ title, children }) => <section role="dialog" aria-label={title}>{children}</section>,
}));

const trip = (overrides = {}) => ({ id: 'trip-id', owner_id: 'user-me', name: 'Tahoe & Reno', currency: 'USD', revision: 4, created_at: '2026-10-01',
  members: [
    { id: 'me', user_id: 'user-me', name: 'Matt', venmo_username: 'mattsho', venmo_confirmed: true, venmo_source: 'account' },
    { id: 'andrew', user_id: 'user-andrew', name: 'Andrew', venmo_username: 'andsohn', venmo_confirmed: false, venmo_source: 'account' },
    { id: 'jason', user_id: null, name: 'Jason', venmo_username: null, venmo_confirmed: false, venmo_source: null },
    { id: 'aziz', user_id: 'user-aziz', name: 'Aziz', venmo_username: 'azizrahman111', venmo_confirmed: true, venmo_source: 'account' },
  ],
  balances: { me: -19318, andrew: 19818, jason: -600, aziz: 100 }, total_minor: 0, expenses: [], repayments: [], activity: [],
  transfers: [{ from_member: 'me', to_member: 'andrew', amount_minor: 19818 }, { from_member: 'jason', to_member: 'me', amount_minor: 500 },
    { from_member: 'jason', to_member: 'aziz', amount_minor: 100 }],
  ...overrides });

beforeEach(() => {
  mocked.request.mockReset();
  vi.stubGlobal('scrollTo', vi.fn());
  mocked.auth = { loading: false, error: '', supabase: {}, signIn: vi.fn(), signOut: vi.fn(),
    user: { id: 'user-me', user_metadata: { full_name: 'Matt' } },
    profile: { user_id: 'user-me', display_name: 'Matt', venmo_username: 'mattsho' } };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function open(path, group = trip()) {
  mocked.request.mockImplementation((_client, _path, method) => method ? Promise.reject(new Error(`Unexpected ${method}`)) : Promise.resolve(group));
  render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/trips/:tripId" element={<TripsApp />} />
  </Routes></MemoryRouter>);
}
const writes = () => mocked.request.mock.calls.filter((call) => call[2]);

it('prepares a Venmo payment for review without changing the ledger, then records it once', async () => {
  open('/trips/trip-id?tab=balances');
  fireEvent.click(await screen.findByRole('button', { name: 'Pay Andrew with Venmo' }));
  const dialog = screen.getByRole('dialog', { name: 'Pay with Venmo' });
  expect(dialog).toHaveTextContent('@andsohn');
  expect(dialog).toHaveTextContent('$198.18');
  expect(within(dialog).getByRole('link', { name: '@andsohn' })).toHaveAttribute('href', 'https://venmo.com/u/andsohn');
  expect(within(dialog).getByRole('button', { name: 'Copy amount' })).toHaveTextContent('Copy amount · $198.18');
  expect(dialog).toHaveTextContent('not by Andrew. Check the name in Venmo.');
  const link = within(dialog).getByRole('link', { name: /Open Venmo to pay/ });
  const url = new URL(link.getAttribute('href'));
  expect([url.pathname, url.searchParams.get('txn'), url.searchParams.get('amount'), url.searchParams.get('note')])
    .toEqual(['/andsohn', 'pay', '198.18', 'Tahoe & Reno · Cozy Trips']);
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  link.addEventListener('click', (event) => event.preventDefault());
  fireEvent.click(link);
  expect(writes()).toEqual([]);
  expect(dialog).toHaveTextContent('After you pay in Venmo, record it here.');

  const failure = Object.assign(new Error('Could not confirm this saved.'), { uncertain: true });
  mocked.request.mockRejectedValueOnce(failure).mockResolvedValueOnce(trip({ revision: 5 }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Mark as paid' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Could not confirm');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Mark as paid' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  const [first, retry] = writes();
  expect(first[1]).toBe('/groups/trip-id/repayments');
  expect(first[3]).toMatchObject({ from_member: 'me', to_member: 'andrew', amount_minor: 19818, notes: 'Venmo', revision: 4 });
  expect(retry[3].id).toBe(first[3].id); // A retry reuses the ID, so the server can't save it twice.
  expect(screen.getByRole('status')).toHaveTextContent('Recorded Matt → Andrew, $198.18.');
  expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
});

it('offers request to the creditor, nothing to bystanders, and a fallback without a username', async () => {
  open('/trips/trip-id?tab=balances');
  expect(await screen.findByRole('button', { name: 'Request from Jason with Venmo' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Aziz with Venmo/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Record payment from Jason to Aziz' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Request from Jason with Venmo' }));
  const dialog = screen.getByRole('dialog', { name: 'Request with Venmo' });
  expect(dialog).toHaveTextContent('Jason hasn’t added a Venmo username.');
  expect(within(dialog).queryByRole('link')).not.toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: 'Copy amount' })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Add it' }));
  expect(await screen.findByRole('tab', { name: 'People', selected: true })).toBeInTheDocument();
  expect(writes()).toEqual([]);
});

it('does not offer Venmo for non-dollar trips', async () => {
  open('/trips/trip-id?tab=balances', trip({ currency: 'EUR' }));
  expect(await screen.findByRole('button', { name: 'Record payment from Matt to Andrew' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /with Venmo/ })).not.toBeInTheDocument();
});

it('keeps the draft and reloads the trip when someone else saved first', async () => {
  open('/trips/trip-id');
  fireEvent.click(await screen.findByRole('button', { name: 'Add expense' }));
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Groceries' } });
  fireEvent.change(screen.getByLabelText('Amount (USD)'), { target: { value: '64.20' } });
  const conflict = Object.assign(new Error('Someone changed this trip.'), { status: 409 });
  mocked.request.mockRejectedValueOnce(conflict).mockResolvedValueOnce(trip({ revision: 9 }));
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The latest version is loaded and your entry is kept');
  expect(screen.getByLabelText('Description')).toHaveValue('Groceries');
  mocked.request.mockResolvedValueOnce(trip({ revision: 10 }));
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  const posts = writes();
  expect(posts.map((call) => call[3].revision)).toEqual([4, 9]);
  expect(posts[1][3].id).toBe(posts[0][3].id);
});

it('opens an unsaved prefilled expense from a link and keeps sections addressable', async () => {
  open('/trips/trip-id?add=expense&description=Dinner&amount=42.50&paid_by=andrew');
  const dialog = await screen.findByRole('dialog', { name: 'Add expense' });
  expect(within(dialog).getByLabelText('Description')).toHaveValue('Dinner');
  expect(within(dialog).getByRole('radio', { name: 'Andrew' })).toBeChecked();
  expect(writes()).toEqual([]);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  fireEvent.click(screen.getByRole('tab', { name: 'People' }));
  expect(screen.getByRole('tabpanel', { name: 'People' })).toHaveTextContent('@andsohn');
  expect(screen.getByRole('button', { name: 'Set Venmo for Jason' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Set Venmo for Andrew' })).not.toBeInTheDocument();
});

it('lets the trip creator set a username for someone who has not joined', async () => {
  open('/trips/trip-id?tab=people');
  fireEvent.click(await screen.findByRole('button', { name: 'Set Venmo for Jason' }));
  fireEvent.change(screen.getByLabelText('Venmo username'), { target: { value: 'no' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('5–30 letters');
  expect(writes()).toEqual([]);
  mocked.request.mockResolvedValueOnce(trip({ revision: 5 }));
  fireEvent.change(screen.getByLabelText('Venmo username'), { target: { value: '@jason-k' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
  expect(writes()[0].slice(1)).toEqual(['/groups/trip-id/members/jason/venmo', 'PUT', { venmo_username: 'jason-k', revision: 4 }]);
});

it('gives the NITEHARTS trip its heart icon only while that trip is open', async () => {
  open('/trips/trip-id', trip({ name: 'NITEHARTS 26' }));
  await screen.findByRole('heading', { name: 'NITEHARTS 26' });
  const icons = () => [...document.head.querySelectorAll('link[href^="/trips/niteharts/"]')].map((link) => `${link.rel} ${link.getAttribute('href')}`);
  expect(icons()).toEqual(['icon /trips/niteharts/favicon.svg', 'icon /trips/niteharts/favicon-32.png', 'apple-touch-icon /trips/niteharts/apple-touch-icon.png']);
  cleanup();
  expect(icons()).toEqual([]);
  open('/trips/trip-id');
  await screen.findByRole('heading', { name: 'Tahoe & Reno' });
  expect(icons()).toEqual([]);
});
