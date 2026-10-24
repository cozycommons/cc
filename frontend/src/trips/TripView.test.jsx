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
  expect(within(dialog).getByRole('button', { name: 'Copy amount' })).toBeInTheDocument();
  expect(dialog).toHaveTextContent('not by Andrew. Check the name in Venmo.');
  // Opening Venmo is the main step; marking it paid only takes the lead once Venmo was opened.
  expect(within(dialog).getByRole('button', { name: 'Mark as paid' })).toHaveClass('cc-button--ghost');
  const link = within(dialog).getByRole('link', { name: /Open Venmo to pay/ });
  const url = new URL(link.getAttribute('href'));
  expect([url.pathname, url.searchParams.get('txn'), url.searchParams.get('amount'), url.searchParams.get('note')])
    .toEqual(['/andsohn', 'pay', '198.18', 'Tahoe & Reno · Cozy Trips']);
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  link.addEventListener('click', (event) => event.preventDefault());
  fireEvent.click(link);
  expect(writes()).toEqual([]);
  expect(dialog).toHaveTextContent('After you pay in Venmo, mark it here.');
  expect(within(dialog).getByRole('button', { name: 'Mark as paid' })).toHaveClass('cc-button--primary');

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

it('offers request to the creditor, nothing to bystanders, and adds a missing username without leaving', async () => {
  open('/trips/trip-id?tab=balances');
  expect(await screen.findByRole('button', { name: 'Request from Jason with Venmo' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Aziz with Venmo/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Record payment from Jason to Aziz' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Request from Jason with Venmo' }));
  const dialog = screen.getByRole('dialog', { name: 'Request with Venmo' });
  expect(dialog).toHaveTextContent('No Venmo username yet');
  expect(within(dialog).queryByRole('link')).not.toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: 'Copy amount' })).toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: 'Mark as received' })).toHaveClass('cc-button--secondary');
  const named = trip({ revision: 5, members: trip().members.map((m) => (m.id === 'jason' ? { ...m, venmo_username: 'jason-k', venmo_source: 'trip' } : m)) });
  mocked.request.mockResolvedValueOnce(named);
  fireEvent.change(within(dialog).getByLabelText('Jason’s Venmo username'), { target: { value: '@jason-k' } });
  await act(async () => fireEvent.click(within(dialog).getByRole('button', { name: 'Add' })));
  expect(writes()[0].slice(1)).toEqual(['/groups/trip-id/members/jason/venmo', 'PUT', { venmo_username: 'jason-k', revision: 4 }]);
  const still = screen.getByRole('dialog', { name: 'Request with Venmo' });
  expect(within(still).getByRole('link', { name: /Open Venmo to request/ })).toHaveAttribute('href', expect.stringContaining('/jason-k?txn=charge'));
  expect(still).toHaveTextContent('Added by the trip creator, not by Jason.');
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
  fireEvent.click(screen.getByRole('button', { name: 'Manage Andrew' }));
  const sheet = screen.getByRole('dialog', { name: 'Andrew' });
  expect(within(sheet).queryByRole('button', { name: /Venmo username/ })).not.toBeInTheDocument();
  expect(sheet).toHaveTextContent('Andrew manages their own name and Venmo from their profile.');
});

it('lets the trip creator set a username for someone who has not joined', async () => {
  open('/trips/trip-id?tab=people');
  fireEvent.click(await screen.findByRole('button', { name: 'Manage Jason' }));
  fireEvent.click(screen.getByRole('button', { name: /Add Venmo username/ }));
  fireEvent.change(screen.getByLabelText('Venmo username'), { target: { value: 'no' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('5–30 letters');
  expect(writes()).toEqual([]);
  mocked.request.mockResolvedValueOnce(trip({ revision: 5 }));
  fireEvent.change(screen.getByLabelText('Venmo username'), { target: { value: '@jason-k' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save' })));
  expect(writes()[0].slice(1)).toEqual(['/groups/trip-id/members/jason/venmo', 'PUT', { venmo_username: 'jason-k', revision: 4 }]);
});

const dinner = { id: 'dinner', description: 'Dinner', amount_minor: 3000, paid_by: 'me', split_mode: 'equal', date: '2026-10-20',
  created_at: '2026-10-20T19:00:00Z', created_by: 'user-me', updated_at: '2026-10-20T19:00:00Z', category: 'food', notes: '',
  shares: { me: 1500, andrew: 1500 } };

it('shows payments in the expense feed next to expenses', async () => {
  open('/trips/trip-id', trip({ expenses: [dinner], repayments: [{ id: 'p1', from_member: 'andrew', to_member: 'me', amount_minor: 1500,
    date: '2026-10-21', notes: 'Venmo', created_at: '2026-10-21T10:00:00Z' }] }));
  const payment = await screen.findByRole('button', { name: 'Payment: Andrew paid Matt $15.00 on 2026-10-21' });
  expect(payment).toHaveTextContent('Andrew paid you');
  expect(payment).toHaveTextContent('you received');
  fireEvent.click(payment);
  expect(screen.getByRole('dialog', { name: 'Remove this payment?' })).toHaveTextContent('Andrew paid Matt');
});

it('hides search until there is something to search', async () => {
  open('/trips/trip-id');
  expect(await screen.findByText('Nothing spent yet. Add the first receipt.')).toBeInTheDocument();
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
});

it('deletes an expense with an undo that restores the same record', async () => {
  open('/trips/trip-id', trip({ expenses: [dinner] }));
  fireEvent.click(await screen.findByRole('button', { name: /^Open Dinner/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('dialog', { name: 'Dinner' })).toBeInTheDocument(); // Cancel goes back, not out.
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  mocked.request.mockResolvedValueOnce(trip({ revision: 5 })).mockResolvedValueOnce(trip({ revision: 6, expenses: [dinner] }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Delete expense' })));
  expect(screen.getByRole('status')).toHaveTextContent('Deleted Dinner.');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Undo' })));
  expect(writes().map((call) => call.slice(1, 3))).toEqual([['/groups/trip-id/expenses/dinner', 'DELETE'], ['/groups/trip-id/expenses/dinner/restore', 'POST']]);
  expect(screen.getByRole('status')).toHaveTextContent('Restored Dinner.');
});

it('shows amounts in activity and restores a deleted expense from it', async () => {
  const activity = [{ id: 'a2', user_id: 'user-me', summary: 'Deleted Dinner', at: '2026-10-21T10:00:00Z', kind: 'delete_expense', item_id: 'dinner', amount_minor: 3000, expense: dinner },
    { id: 'a1', user_id: 'user-me', summary: 'Added Dinner', at: '2026-10-20T19:00:00Z', kind: 'add_expense', item_id: 'dinner', amount_minor: 3000 }];
  open('/trips/trip-id?tab=activity', trip({ activity }));
  expect(await screen.findByText('Deleted Dinner')).toBeInTheDocument();
  expect(screen.getAllByText('$30.00')).toHaveLength(2);
  mocked.request.mockResolvedValueOnce(trip({ revision: 5, expenses: [dinner], activity }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Restore' })));
  expect(writes()[0].slice(1, 3)).toEqual(['/groups/trip-id/expenses/dinner/restore', 'POST']);
  expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Added Dinner. Open it' })).toBeInTheDocument();
});

it('lets the creator rename or remove people and blocks removing someone on the ledger', async () => {
  open('/trips/trip-id?tab=people', trip({ expenses: [dinner] }));
  fireEvent.click(await screen.findByRole('button', { name: 'Manage Andrew' }));
  expect(screen.getByRole('button', { name: /Remove from trip/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Manage Jason' }));
  fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Jase' } });
  mocked.request.mockResolvedValueOnce(trip({ revision: 5 }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save name' })));
  expect(writes()[0].slice(1)).toEqual(['/groups/trip-id/members/jason', 'PUT', { name: 'Jase', revision: 4 }]);
  fireEvent.click(screen.getByRole('button', { name: 'Manage Jason' }));
  fireEvent.click(screen.getByRole('button', { name: /Remove from trip/ }));
  mocked.request.mockResolvedValueOnce(trip({ revision: 6 }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Remove' })));
  expect(writes()[1].slice(1)).toEqual(['/groups/trip-id/members/jason', 'DELETE', { revision: 5 }]);
});

it('renames and deletes the trip from trip settings', async () => {
  open('/trips/trip-id?tab=people');
  fireEvent.click(await screen.findByRole('button', { name: 'Trip settings' }));
  fireEvent.change(screen.getByLabelText('Trip name'), { target: { value: 'Tahoe' } });
  mocked.request.mockResolvedValueOnce(trip({ revision: 5, name: 'Tahoe' }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save name' })));
  expect(writes()[0].slice(1)).toEqual(['/groups/trip-id', 'PUT', { name: 'Tahoe', revision: 4 }]);
  expect(screen.getByRole('heading', { name: 'Tahoe', level: 1 })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Trip settings' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete trip' }));
  expect(screen.getByRole('dialog', { name: 'Delete this trip?' })).toHaveTextContent('can’t be undone');
  mocked.request.mockResolvedValueOnce({ deleted: 'trip-id' });
  await act(async () => fireEvent.click(screen.getAllByRole('button', { name: 'Delete trip' }).at(-1)));
  expect(writes()[1].slice(1)).toEqual(['/groups/trip-id', 'DELETE', { revision: 5 }]);
});

it('picks up other people’s changes when the person comes back to the page', async () => {
  open('/trips/trip-id');
  expect(await screen.findByText('Nothing spent yet. Add the first receipt.')).toBeInTheDocument();
  mocked.request.mockResolvedValueOnce(trip({ revision: 5, expenses: [dinner] }));
  await act(async () => document.dispatchEvent(new Event('visibilitychange')));
  expect(await screen.findByRole('button', { name: /^Open Dinner/ })).toBeInTheDocument();
});

it('keeps an open draft when Undo is tapped on a notice', async () => {
  open('/trips/trip-id', trip({ expenses: [dinner] }));
  fireEvent.click(await screen.findByRole('button', { name: /^Open Dinner/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  mocked.request.mockResolvedValueOnce(trip({ revision: 5 })).mockResolvedValueOnce(trip({ revision: 6, expenses: [dinner] }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Delete expense' })));
  fireEvent.click(screen.getByRole('button', { name: 'Add expense' }));
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Half-typed' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Undo' })));
  expect(screen.getByRole('dialog', { name: 'Add expense' })).toBeInTheDocument();
  expect(screen.getByLabelText('Description')).toHaveValue('Half-typed');
});

it('only offers Restore while everyone on the deleted expense is still on the trip', async () => {
  const gone = { ...dinner, shares: { me: 1500, someone: 1500 } };
  open('/trips/trip-id?tab=activity', trip({ activity: [{ id: 'a1', user_id: 'user-me', summary: 'Deleted Dinner', at: '2026-10-21T10:00:00Z',
    kind: 'delete_expense', item_id: 'dinner', amount_minor: 3000, expense: gone }] }));
  expect(await screen.findByText('Deleted Dinner')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument();
});

it('reloads before deleting a trip that changed, and treats a retried delete that finds nothing as done', async () => {
  open('/trips/trip-id?tab=people');
  fireEvent.click(await screen.findByRole('button', { name: 'Trip settings' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete trip' }));
  const conflict = Object.assign(new Error('Someone changed this trip.'), { status: 409 });
  mocked.request.mockRejectedValueOnce(conflict).mockResolvedValueOnce(trip({ revision: 7 }));
  await act(async () => fireEvent.click(screen.getAllByRole('button', { name: 'Delete trip' }).at(-1)));
  expect(screen.getByRole('alert')).toHaveTextContent('Check the latest totals, then delete again.');
  const gone = Object.assign(new Error('Trip not found or you are not a member.'), { status: 404 });
  mocked.request.mockRejectedValueOnce(gone);
  await act(async () => fireEvent.click(screen.getAllByRole('button', { name: 'Delete trip' }).at(-1)));
  const deletes = writes().filter((call) => call[2] === 'DELETE');
  expect(deletes.map((call) => call[3].revision)).toEqual([4, 7]);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('leaves a trip that was deleted while it was open', async () => {
  open('/trips/trip-id');
  expect(await screen.findByText('Nothing spent yet. Add the first receipt.')).toBeInTheDocument();
  mocked.request.mockRejectedValueOnce(Object.assign(new Error('Trip not found or you are not a member.'), { status: 404 }));
  await act(async () => document.dispatchEvent(new Event('visibilitychange')));
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Tahoe & Reno' })).not.toBeInTheDocument());
});
