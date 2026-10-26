import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Admin from './Admin.jsx';
import { MemoryRouter } from 'react-router-dom';
import { adminRequest } from './api.js';
vi.mock('./api.js', () => ({ adminRequest: vi.fn() }));
vi.mock('./Chart.jsx', () => ({ default: ({ result }) => <div>{JSON.stringify(result.rows)}</div> }));
vi.mock('../supabase.js', () => ({ getClient: () => ({ auth: { onAuthStateChange: () => ({ data: { subscription: { unsubscribe: vi.fn() } } }), signInWithOAuth: vi.fn() } }) }));
afterEach(cleanup);
beforeEach(() => {
  adminRequest.mockReset();
  adminRequest.mockImplementation(async (path) => {
    if (path === '/session') return { id: 'admin' };
    if (path === '/queries') return [];
    if (path === '/catalog') return { views: [] };
    if (path === '/query') return { columns: ['events'], rows: [{ events: 42 }], truncated: false };
  });
});
it('shows sign-in for anonymous access and denies ordinary accounts', async () => {
  adminRequest.mockRejectedValue(Object.assign(new Error('Sign in to continue.'), { status: 401 }));
  render(<MemoryRouter><Admin /></MemoryRouter>);
  expect(await screen.findByRole('button', { name: 'Sign in with Google' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Cozy Commons home' })).toHaveAttribute('href', '/');
  expect(screen.getByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin');
});
it('runs a draft without saving and clears results when filters change', async () => {
  render(<MemoryRouter><Admin /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'New query' }));
  fireEvent.click(screen.getByRole('button', { name: 'Run' }));
  expect(await screen.findByText('[{"events":42}]')).toBeInTheDocument();
  expect(adminRequest.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'dice' } });
  await waitFor(() => expect(screen.queryByText('[{"events":42}]')).not.toBeInTheDocument());
});
it('saves named SQL and visualization settings', async () => {
  render(<MemoryRouter><Admin /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'New query' }));
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'My chart' } });
  adminRequest.mockImplementation(async (path, options) => {
    if (path === '/queries' && options?.method === 'POST') return { id: 'saved', ...options.body };
    if (path === '/queries') return [];
    if (path === '/catalog') return { views: [] };
    return {};
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(adminRequest).toHaveBeenCalledWith('/queries', expect.objectContaining({ method: 'POST', body: expect.objectContaining({ title: 'My chart', visualization: expect.objectContaining({ type: 'table' }) }) })));
});

it('saves the shared view selector value', async () => {
  render(<MemoryRouter><Admin /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'New query' }));
  fireEvent.click(screen.getByRole('radio', { name: 'Bar' }));
  expect(screen.getByRole('radio', { name: 'Bar' })).toBeChecked();
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Counts' } });
  adminRequest.mockImplementation(async (path, options) => {
    if (path === '/queries' && options?.method === 'POST') return { id: 'saved', ...options.body };
    if (path === '/queries') return [];
    if (path === '/catalog') return { views: [] };
    return {};
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(adminRequest).toHaveBeenCalledWith('/queries', expect.objectContaining({ body: expect.objectContaining({ visualization: expect.objectContaining({ type: 'bar' }) }) })));
});

it('keeps existing chart data visible while refreshing', async () => {
  const query = { id: 'one', title: 'Users', sql: 'SELECT 1', revision: 1, visualization: { type: 'table' } };
  let finishRefresh;
  let runs = 0;
  adminRequest.mockImplementation(async (path) => {
    if (path === '/session') return { id: 'admin' };
    if (path === '/queries') return [query];
    if (path === '/catalog') return { views: [] };
    if (path.endsWith('/run')) {
      runs++;
      if (runs === 1) return { rows: [{ users: 12 }] };
      return new Promise((resolve) => { finishRefresh = resolve; });
    }
  });
  render(<MemoryRouter><Admin /></MemoryRouter>);
  expect(await screen.findByText('[{"users":12}]')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  expect(await screen.findByText('Refreshing…')).toBeInTheDocument();
  expect(screen.getByText('[{"users":12}]')).toBeInTheDocument();
  finishRefresh({ rows: [{ users: 13 }] });
  expect(await screen.findByText('[{"users":13}]')).toBeInTheDocument();
});
