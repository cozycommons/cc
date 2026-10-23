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
    expect(await screen.findByRole('button', { name: /Edit Dinner/ })).toBeInTheDocument();
    await act(async () => finishRefresh(group(1)));
    expect(screen.getByRole('button', { name: /Edit Dinner/ })).toBeInTheDocument();
  });

  it('saves a draft against the version it was opened from and shows what changed on conflict', async () => {
    let finishRefresh;
    mocked.request.mockResolvedValueOnce(group(1, [dinner('')]));
    open();
    mocked.request.mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh trip' }));
    fireEvent.click(screen.getByRole('button', { name: /Edit Dinner/ }));
    await act(async () => finishRefresh(group(2, [dinner('Sam changed this')])));
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Dinner out' } });
    mocked.request.mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 409 })).mockResolvedValueOnce(group(2, [dinner('Sam changed this')]));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit expense' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('your entry is kept');
    expect(within(dialog).getByText(/Now saved as Dinner · \$20.00 · paid by Matt/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Description')).toHaveValue('Dinner out');
    const puts = mocked.request.mock.calls.filter((call) => call[2] === 'PUT');
    expect(puts.map((call) => call[3].revision)).toEqual([1]); // Opened at revision 1, not silently rebased to 2.
    mocked.request.mockResolvedValueOnce(group(3, [{ ...dinner('Sam changed this'), description: 'Dinner out' }]));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocked.request.mock.calls.filter((call) => call[2] === 'PUT').map((call) => call[3].revision)).toEqual([1, 2]);
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
    expect(mocked.request.mock.calls.some((call) => call[2] === 'PUT')).toBe(false);
  });
});
