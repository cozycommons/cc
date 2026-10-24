// Regressions from the adversarial review: StrictMode forms, stale refreshes, draft base revisions,
// truncated responses, currency symbols and own-profile saves across account changes.
import React from 'react';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toMinor } from './money.js';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('forms under StrictMode', () => {
  it('shows a failed save instead of staying locked', async () => {
    const { Form, Field } = await vi.importActual('./ui.jsx');
    render(<React.StrictMode><Form submit="Save" onCancel={() => {}} onSubmit={() => Promise.reject(new Error('Network down'))}>
      <Field label="Name"><input defaultValue="Draft" /></Field></Form></React.StrictMode>);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Network down');
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByLabelText('Name')).toHaveValue('Draft');
  });
});

describe('money input currency', () => {
  it('rejects another currency symbol instead of silently converting', () => {
    expect(() => toMinor('€12', false, 'USD')).toThrow('This trip uses USD');
    expect(() => toMinor('$12', false, 'EUR')).toThrow('This trip uses EUR');
    expect(toMinor('€12', false, 'EUR')).toBe(1200);
    expect(toMinor('$12', false, 'CAD')).toBe(1200);
  });
});

describe('API responses', () => {
  it('treats a cut-off successful write as uncertain, not as an empty trip', async () => {
    const { tripRequest } = await vi.importActual('./api.js');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 201, json: () => Promise.reject(new SyntaxError('Unexpected end')) }));
    const supabase = { auth: { getSession: () => Promise.resolve({ data: { session: { access_token: 't' } } }) } };
    await expect(tripRequest(supabase, '/groups/x/expenses', 'POST', {})).rejects.toMatchObject({ uncertain: true, message: expect.stringContaining('won’t be duplicated') });
  });
  it('surfaces validation messages from the server', async () => {
    const { tripRequest } = await vi.importActual('./api.js');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: () => Promise.resolve({ detail: [{ msg: 'Value error, Use 5–30 letters' }] }) }));
    const supabase = { auth: { getSession: () => Promise.resolve({ data: { session: { access_token: 't' } } }) } };
    await expect(tripRequest(supabase, '/me', 'PUT', {})).rejects.toMatchObject({ status: 422, message: 'Use 5–30 letters' });
  });
});

const mocked = vi.hoisted(() => ({ auth: null, request: vi.fn(), context: null }));
vi.mock('./api.js', async (importOriginal) => ({ ...await importOriginal(), tripRequest: (...args) => mocked.request(...args) }));
vi.mock('../contexts/SupabaseContext.jsx', () => ({ useSupabase: () => mocked.context }));

describe('trip state', () => {
  let TripsApp;
  beforeEach(async () => {
    vi.resetModules();
    vi.doMock('./useTripsAuth.js', () => ({ useTripsAuth: () => mocked.auth, localDemo: false }));
    vi.doMock('./ui.jsx', async () => ({ ...await vi.importActual('./ui.jsx'),
      Modal: ({ title, children }) => <section role="dialog" aria-label={title}>{children}</section> }));
    TripsApp = (await import('./TripsApp.jsx')).default;
    mocked.request.mockReset();
    vi.stubGlobal('scrollTo', vi.fn());
    mocked.auth = { loading: false, error: '', supabase: {}, user: { id: 'user-a', user_metadata: {} }, profile: { user_id: 'user-a', display_name: 'Matt' } };
  });
  const group = (revision, expenses = []) => ({ id: 'trip-id', owner_id: 'user-a', name: 'Trip', currency: 'USD', revision, created_at: '2026-10-01',
    members: [{ id: 'a', user_id: 'user-a', name: 'Matt' }, { id: 'b', user_id: null, name: 'Sam' }],
    balances: { a: 0, b: 0 }, transfers: [], repayments: [], activity: [], total_minor: 0, expenses });
  const dinner = (notes) => ({ id: 'e1', description: 'Dinner', amount_minor: 2000, paid_by: 'a', date: '2026-10-20', created_at: '2026-10-20T00:00:00Z',
    category: 'food', notes, split_mode: 'equal', shares: { a: 1000, b: 1000 } });
  const open = () => render(<MemoryRouter initialEntries={['/trips/trip-id']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Routes><Route path="/trips/:tripId" element={<TripsApp />} /></Routes></MemoryRouter>);

  it('never lets a slow refresh hide a newer save', async () => {
    let finishRefresh;
    mocked.request.mockResolvedValueOnce(group(1));
    open();
    await screen.findByRole('heading', { name: 'Trip' });
    mocked.request.mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh trip' }));
    mocked.request.mockResolvedValueOnce(group(2, [dinner('')]));
    fireEvent.click(screen.getByRole('button', { name: 'Add expense' }));
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Dinner' } });
    fireEvent.change(screen.getByLabelText('Amount (USD)'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
    expect(await screen.findByRole('button', { name: /Open Dinner/ })).toBeInTheDocument();
    await act(async () => finishRefresh(group(1)));
    expect(screen.getByRole('button', { name: /Open Dinner/ })).toBeInTheDocument();
  });

  it('saves a draft against the version it was opened from and shows what changed on conflict', async () => {
    let finishRefresh;
    mocked.request.mockResolvedValueOnce(group(1, [dinner('')]));
    open();
    mocked.request.mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh trip' }));
    fireEvent.click(screen.getByRole('button', { name: /Open Dinner/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await act(async () => finishRefresh(group(2, [dinner('Sam changed this')])));
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Dinner out' } });
    mocked.request.mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 409 })).mockResolvedValueOnce(group(2, [dinner('Sam changed this')]));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit expense' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('your entry is kept');
    expect(within(dialog).getByText('Dinner · $20.00 · Matt paid')).toBeInTheDocument();
    expect(within(dialog).getByText('Equally: Matt $10.00, Sam $10.00')).toBeInTheDocument();
    expect(within(dialog).getByText(/“Sam changed this”/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Description')).toHaveValue('Dinner out');
    const puts = mocked.request.mock.calls.filter((call) => call[2] === 'PUT');
    expect(puts.map((call) => call[3].revision)).toEqual([1]); // Opened at revision 1, not silently rebased to 2.
    mocked.request.mockResolvedValueOnce(group(3, [{ ...dinner('Sam changed this'), description: 'Dinner out' }]));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocked.request.mock.calls.filter((call) => call[2] === 'PUT').map((call) => call[3].revision)).toEqual([1, 2]);
  });
});

describe('trip state, round 2', () => {
  let TripsApp;
  beforeEach(async () => {
    vi.resetModules();
    vi.doMock('./useTripsAuth.js', () => ({ useTripsAuth: () => mocked.auth, localDemo: false }));
    vi.doMock('./ui.jsx', async () => ({ ...await vi.importActual('./ui.jsx'),
      Modal: ({ title, children }) => <section role="dialog" aria-label={title}>{children}</section> }));
    TripsApp = (await import('./TripsApp.jsx')).default;
    mocked.request.mockReset();
    vi.stubGlobal('scrollTo', vi.fn());
    mocked.auth = { loading: false, error: '', supabase: {}, user: { id: 'user-a', user_metadata: {} }, profile: { user_id: 'user-a', display_name: 'Matt' } };
  });
  const group = (revision, expenses = [], extra = []) => ({ id: 'trip-id', owner_id: 'user-a', name: 'Trip', currency: 'USD', revision, created_at: '2026-10-01',
    members: [{ id: 'a', user_id: 'user-a', name: 'Matt' }, { id: 'b', user_id: null, name: 'Sam' }, ...extra],
    balances: { a: 0, b: 0 }, transfers: [], repayments: [], activity: [], total_minor: 0, expenses });
  const dinner = { id: 'e1', description: 'Dinner', amount_minor: 2000, paid_by: 'a', date: '2026-10-20', created_at: '2026-10-20T00:00:00Z',
    category: 'food', notes: '', split_mode: 'equal', shares: { a: 1000, b: 1000 } };
  const open = (path = '/trips/trip-id') => render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Routes><Route path="/trips/:tripId" element={<TripsApp />} /></Routes></MemoryRouter>);

  it('deletes from the editor against the version the editor showed', async () => {
    let finishRefresh;
    mocked.request.mockResolvedValueOnce(group(1, [dinner]));
    open();
    mocked.request.mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh trip' }));
    fireEvent.click(screen.getByRole('button', { name: /Open Dinner/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await act(async () => finishRefresh(group(2, [{ ...dinner, description: 'Hotel', amount_minor: 20000 }])));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    mocked.request.mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 409 })).mockResolvedValueOnce(group(2, [{ ...dinner, description: 'Hotel', amount_minor: 20000 }]));
    fireEvent.click(screen.getByRole('button', { name: 'Delete expense' }));
    const confirm = await screen.findByRole('dialog', { name: 'Delete this expense?' });
    expect(await within(confirm).findByText('Someone changed this expense. Delete this version?')).toBeInTheDocument();
    expect(within(confirm).getByText('Hotel · $200.00 · Matt paid')).toBeInTheDocument();
    const deletes = mocked.request.mock.calls.filter((call) => call[2] === 'DELETE');
    expect(deletes.map((call) => call[3].revision)).toEqual([1]);
  });

  it('keeps earlier invite links when a multi-add is retried after a partial failure', async () => {
    const sam2 = { id: 'c', user_id: null, name: 'Alex' };
    mocked.request.mockResolvedValueOnce(group(1));
    open('/trips/trip-id?tab=people');
    fireEvent.click(await screen.findByRole('button', { name: 'Add people' }));
    fireEvent.change(screen.getByLabelText('Names'), { target: { value: 'Alex, Jordan' } });
    mocked.request.mockResolvedValueOnce({ group: group(2, [], [sam2]), invite_token: 'alex-token' })
      .mockRejectedValueOnce(new Error('Network down'));
    fireEvent.click(screen.getByRole('button', { name: 'Add 2 people' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Added Alex. Could not add Jordan');
    mocked.request.mockResolvedValueOnce({ group: group(3, [], [sam2, { id: 'd', user_id: null, name: 'Jordan' }]), invite_token: 'jordan-token' });
    fireEvent.click(screen.getByRole('button', { name: 'Add 2 people' }));
    const links = await screen.findByRole('dialog', { name: 'Invite links' });
    expect(within(links).getByRole('textbox', { name: 'Invite link for Alex' }).value).toContain('alex-token');
    expect(within(links).getByRole('textbox', { name: 'Invite link for Jordan' }).value).toContain('jordan-token');
    const posts = mocked.request.mock.calls.filter((call) => call[2] === 'POST').map((call) => call[3].name);
    expect(posts).toEqual(['Alex', 'Jordan', 'Jordan']);
  });

  it('locks Remove while a Venmo save is pending and routes it through the form', async () => {
    const { VenmoForm } = await vi.importActual('./People.jsx');
    let finish;
    const save = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    render(<VenmoForm initial="old-handle" onSave={save} onCancel={() => {}} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Venmo username' }), { target: { value: 'new-handle' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByRole('button', { name: 'Remove' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(save.mock.calls).toEqual([['new-handle']]);
    await act(async () => finish());
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(save.mock.calls).toEqual([['new-handle'], [null]]));
  });
});

describe('account-bound writes', () => {
  it('sends nothing when the session no longer belongs to the expected account', async () => {
    const { tripRequest } = await vi.importActual('./api.js');
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const supabase = { auth: { getSession: () => Promise.resolve({ data: { session: { access_token: 'b-token', user: { id: 'user-b' } } } }) } };
    await expect(tripRequest(supabase, '/me', 'PUT', { venmo_username: 'a-handle' }, 'user-a')).rejects.toThrow('Your account changed');
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('own Venmo username', () => {
  it('refuses to save when the signed-in account changed underneath the dialog', async () => {
    const { useTripsAuth } = await vi.importActual('./useTripsAuth.js');
    let current = 'user-a';
    const supabase = { auth: {
      getSession: vi.fn(() => Promise.resolve({ data: { session: { user: { id: current } } } })),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe() {} } } })),
    } };
    mocked.context = { supabase, auth: {} };
    mocked.request.mockReset();
    mocked.request.mockImplementation((_client, path, method) => Promise.resolve(method === 'PUT'
      ? { user_id: current, venmo_username: 'alex-v' } : { user_id: current, display_name: 'A' }));
    const { result } = renderHook(() => useTripsAuth());
    await waitFor(() => expect(result.current.profile?.user_id).toBe('user-a'));
    current = 'user-b';
    await expect(result.current.saveVenmo('alex-v')).rejects.toThrow('Your account changed');
    // The write itself is bound to the account the dialog was opened for (checked against the token it sends).
    const put = mocked.request.mock.calls.find((call) => call[2] === 'PUT');
    expect(put.slice(1)).toEqual(['/me', 'PUT', { venmo_username: 'alex-v' }, 'user-a']);
  });
});
